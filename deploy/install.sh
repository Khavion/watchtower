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
LABEL="com.khavion.agent"
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
if ! ollama list 2>/dev/null | grep -q '^llama3.1:8b'; then
  say "pulling llama3.1:8b (4.9 GB, one-time)"
  ollama pull llama3.1:8b
fi
say "ollama ready (llama3.1:8b present, loopback only)"

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

# 7. LaunchAgent --------------------------------------------------------------
if [ "$NO_AGENT" = "1" ]; then
  warn "--no-agent: skipping LaunchAgent registration (dev machine mode)"
else
  mkdir -p "$HOME/Library/LaunchAgents" data/runs
  sed "s|__REPO__|$REPO|g" deploy/com.khavion.agent.plist > "$AGENT_PLIST"
  UID_NUM="$(id -u)"
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  launchctl enable "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$AGENT_PLIST" \
    || die "launchctl bootstrap failed (see: launchctl print gui/$UID_NUM/$LABEL)"
  sleep 2
  if launchctl print "gui/$UID_NUM/$LABEL" | grep -q "state = running"; then
    say "LaunchAgent running ($LABEL); logs in data/runs/"
  else
    warn "LaunchAgent bootstrapped but not yet running; check:"
    warn "  launchctl print gui/$UID_NUM/$LABEL ; tail data/runs/launchd.err.log"
  fi
  # No-inbound-ports audit: the daemon must own zero LISTEN sockets.
  DAEMON_PIDS="$(pgrep -f 'pipeline.run --daemon' || true)"
  if [ -n "$DAEMON_PIDS" ]; then
    for pid in $DAEMON_PIDS; do
      if lsof -nP -a -p "$pid" -iTCP -sTCP:LISTEN 2>/dev/null | grep -q .; then
        die "daemon (pid $pid) owns a LISTEN socket - this violates the no-inbound-ports rule"
      fi
    done
    say "port audit: daemon owns no listening sockets"
  fi
fi

echo ""
say "install complete."
say "manual next steps that only Zohaib can do:"
echo "    1. Populate brain/blocklist.local.md (never committed, never shown to AI)"
echo "    2. sam.gov: associate your entity -> raises API quota 10/day -> 1,000/day"
echo "    3. Cliq: channel 'khavionagent' must exist (commands: run|status|pause|resume|score|approve|reject)"
