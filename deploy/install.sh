#!/usr/bin/env bash
# Khavion watchtower installer. Idempotent; run after `git pull` on the Mac
# Mini (and safely re-runnable any time). Fails loudly and stops on any
# missing prerequisite rather than continuing in a broken state.
#
# Usage:
#   ./deploy/install.sh              # full install incl. LaunchAgent
#   ./deploy/install.sh --no-agent   # everything except LaunchAgent (dev box)
#
# launchctl syntax verified 2026-07-24: bootstrap/bootout/enable are the
# modern forms (load -w is legacy). `security find-generic-password` is used
# WITHOUT -w so no secret is ever printed.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.khavion.dispatch"
AGENT_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
NO_AGENT=0
[ "${1:-}" = "--no-agent" ] && NO_AGENT=1

say()  { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install][WARN]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[install][FATAL]\033[0m %s\n' "$*" >&2; exit 1; }

cd "$REPO"

# 1. Python >= 3.11 -----------------------------------------------------------
PY=""
for candidate in python3.13 python3.12 python3.11 python3.14 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      PY="$(command -v "$candidate")"
      break
    fi
  fi
done
[ -n "$PY" ] || die "Python 3.11+ not found. Install with: brew install python@3.13"
say "python: $PY ($("$PY" --version 2>&1))"

# 2. venv + pinned dependencies ----------------------------------------------
if [ ! -x .venv/bin/python ]; then
  say "creating .venv"
  "$PY" -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
say "dependencies installed (requirements.txt)"

# 3. Ollama + model -----------------------------------------------------------
command -v ollama >/dev/null 2>&1 \
  || die "ollama not installed. Run: brew install ollama && brew services start ollama"
if ! curl -sf -m 5 http://127.0.0.1:11434/api/tags >/dev/null; then
  warn "ollama server not responding; trying 'brew services start ollama'"
  brew services start ollama >/dev/null 2>&1 || true
  sleep 5
  curl -sf -m 5 http://127.0.0.1:11434/api/tags >/dev/null \
    || die "ollama server still unreachable on 127.0.0.1:11434"
fi
# The workhorse model is whatever config/providers.yaml says, so switching it is
# still a one-line change and the installer never drifts from the config.
WORKHORSE="$(.venv/bin/python -c 'from pipeline.config import providers; print(providers()["ollama"]["model"])')"
[ -n "$WORKHORSE" ] || die "could not read the workhorse model from config/providers.yaml"
if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$WORKHORSE"; then
  say "pulling $WORKHORSE (one-time, several GB)"
  ollama pull "$WORKHORSE"
fi
say "ollama ready ($WORKHORSE present, loopback only)"

# Ollama env must be durable: `launchctl setenv` is the only mechanism that
# reaches the Ollama service, and it is wiped by every reboot. Without this the
# system keeps working but silently truncates long documents to 4096 tokens.
mkdir -p "$HOME/Library/LaunchAgents" data/runs
OLLAMA_ENV_PLIST="$HOME/Library/LaunchAgents/com.khavion.ollamaenv.plist"
sed "s|__REPO__|$REPO|g" deploy/com.khavion.ollamaenv.plist > "$OLLAMA_ENV_PLIST"
launchctl bootout "gui/$(id -u)/com.khavion.ollamaenv" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$OLLAMA_ENV_PLIST" 2>/dev/null || true
./deploy/ollama_env.sh >/dev/null 2>&1 || warn "ollama env script reported a problem; see data/runs/ollamaenv.err.log"
say "ollama environment applied and made durable across reboots"

# 4. Keychain: all six entries must exist ------------------------------------
# Checked WITHOUT -w: exit status only, no secret is read or printed.
# The pre-existing entries khavion-google-client-secret and
# khavion-site-zoho-refresh are never touched by anything in this repo.
MISSING=()
for service in khavion-apollo-api-key khavion-sam-api-key khavion-zoho-client-id \
               khavion-zoho-client-secret khavion-zoho-refresh-token khavion-zoho-region; do
  if security find-generic-password -a khavion -s "$service" >/dev/null 2>&1; then
    say "keychain: $service present"
  else
    MISSING+=("$service")
  fi
done
if [ "${#MISSING[@]}" -gt 0 ]; then
  echo ""
  warn "missing Keychain entries on THIS machine (Keychain does not sync):"
  for m in "${MISSING[@]}"; do echo "    - $m"; done
  cat <<'EOF'
  Fix: run the interactive setup (you type every secret yourself):
      .venv/bin/python deploy/setup_credentials.py all
  or per-service: ... setup_credentials.py apollo | sam | zoho
EOF
  die "credentials incomplete"
fi

# 5. Blocklist ----------------------------------------------------------------
if [ ! -f brain/blocklist.local.md ]; then
  cp brain/blocklist.template.md brain/blocklist.local.md
  warn "created brain/blocklist.local.md from template."
fi
if ! grep -qE '^\| [a-z0-9.-]+ \|' brain/blocklist.local.md \
   || ! grep -vE 'example\.com' brain/blocklist.local.md | grep -qE '^\| [a-z0-9.-]+\.[a-z]+ \|'; then
  warn "brain/blocklist.local.md has NO real entries yet."
  warn "TODO(zohaib): populate it before production use - the employer"
  warn "firewall passes vacuously until it has rows."
fi

# 6. Offline test suite + dry-run smoke test ---------------------------------
say "running offline test suite"
.venv/bin/python -m pytest -q || die "test suite failed"
say "running dry-run smoke test (zero Zoho writes)"
.venv/bin/python -m pipeline.run --dry-run --limit 3 || die "dry-run smoke test failed"

# 7. Job table ----------------------------------------------------------------
# Schedules live in SQLite, not in plists, so adding an agent later is one row.
# Re-registering preserves whatever Zohaib has turned off and never fires a
# backlog: upsert_job only resets a job's next-due time if its schedule changed.
say "registering the agent schedule"
.venv/bin/python -m pipeline.dispatch --register || die "could not register the job table"

# 8. LaunchAgents -------------------------------------------------------------
if [ "$NO_AGENT" = "1" ]; then
  warn "--no-agent: skipping LaunchAgent registration (dev machine mode)"
else
  mkdir -p "$HOME/Library/LaunchAgents" data/runs
  UID_NUM="$(id -u)"

  # The old single long-lived daemon is retired; remove it if this machine ever
  # ran it, or it would keep scheduling alongside the dispatcher.
  if launchctl print "gui/$UID_NUM/com.khavion.agent" >/dev/null 2>&1; then
    warn "removing the retired com.khavion.agent daemon (replaced by the dispatcher)"
    launchctl bootout "gui/$UID_NUM/com.khavion.agent" 2>/dev/null || true
  fi
  rm -f "$HOME/Library/LaunchAgents/com.khavion.agent.plist"

  for label in com.khavion.dispatch com.khavion.cliq com.khavion.awake; do
    plist="$HOME/Library/LaunchAgents/$label.plist"
    sed "s|__REPO__|$REPO|g" "deploy/$label.plist" > "$plist"
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    launchctl enable "gui/$UID_NUM/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_NUM" "$plist" \
      || die "launchctl bootstrap failed for $label (see: launchctl print gui/$UID_NUM/$label)"
    say "registered $label"
  done

  sleep 3
  for label in com.khavion.dispatch com.khavion.cliq; do
    if launchctl print "gui/$UID_NUM/$label" >/dev/null 2>&1; then
      say "$label is loaded and ticking every 60s"
    else
      warn "$label did not load; check: launchctl print gui/$UID_NUM/$label"
    fi
  done

  # No-inbound-ports audit. Nothing this system runs may own a LISTEN socket.
  for pattern in 'pipeline.dispatch' 'pipeline.run'; do
    for pid in $(pgrep -f "$pattern" || true); do
      if lsof -nP -a -p "$pid" -iTCP -sTCP:LISTEN 2>/dev/null | grep -q .; then
        die "pid $pid ($pattern) owns a LISTEN socket - violates the no-inbound-ports rule"
      fi
    done
  done
  say "port audit: nothing this system runs is listening for inbound connections"
fi

echo ""
say "install complete."
say "what only Zohaib can do:"
echo "    1. In the khavionagent Cliq channel, type: block <domain>"
echo "       for every company the system must never contact."
echo "    2. sam.gov: associate your entity -> raises API quota 10/day -> 1,000/day"
echo "    3. Cliq: the channel 'khavionagent' must exist."
echo "       Commands: run | status | pause | resume | agents | brief | triage |"
echo "                 write | score <id> | approve <id> | reject <id> |"
echo "                 proposal <id> | note <anything> | block <domain>"
