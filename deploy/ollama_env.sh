#!/usr/bin/env bash
# Apply Ollama's environment durably and restart it so the settings take.
#
# Why this script exists: Ollama is launched by its own Homebrew LaunchAgent and
# therefore inherits nothing from any shell. `launchctl setenv` is the mechanism
# that reaches it, but those values are session-scoped and disappear on reboot,
# which is a silent failure: everything keeps working, just with a 4096-token
# window and a model that unloads between agent turns. com.khavion.ollamaenv
# runs this at every login so that cannot happen.
#
# Idempotent. Safe to run by hand at any time.

set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Long documents must not be truncated before the model sees them.
launchctl setenv OLLAMA_CONTEXT_LENGTH 16384
# Two loaded models: the workhorse, plus headroom for an A/B comparison.
launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
# Memory multiplies with parallelism. On a 16 GB machine this stays at 1.
launchctl setenv OLLAMA_NUM_PARALLEL 1
# Keep the workhorse resident between agent turns.
launchctl setenv OLLAMA_KEEP_ALIVE 24h
# Loopback only. Nothing on this machine listens to the outside world.
launchctl setenv OLLAMA_HOST 127.0.0.1:11434

echo "$(date '+%Y-%m-%d %H:%M:%S') ollama env applied:"
for v in OLLAMA_CONTEXT_LENGTH OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL \
         OLLAMA_KEEP_ALIVE OLLAMA_HOST; do
  echo "  $v=$(launchctl getenv "$v")"
done

# Restart Ollama so it reads the new environment. `brew services restart` is the
# supported form; if Ollama was never started as a service this starts it.
if command -v brew >/dev/null 2>&1; then
  brew services restart ollama >/dev/null 2>&1 || brew services start ollama >/dev/null 2>&1 || true
fi

# Wait for the API to come back before declaring success; a dispatcher tick that
# lands during the restart window should not be the thing that discovers this.
for _ in $(seq 1 30); do
  if curl -sf -m 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "  ollama API responding"
    exit 0
  fi
  sleep 1
done

echo "  WARNING: ollama API did not come back within 30s" >&2
exit 1
