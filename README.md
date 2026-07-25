# watchtower

Khavion's local lead-generation agent. Its only job is finding paying consulting
work: outbound prospects via Apollo, posted solicitations via public procurement
sources. Outputs are a scored record in Zoho CRM and a draft email in Zoho Mail's
Drafts folder — Zohaib reads and sends every email himself. Nothing auto-sends.

> **Setting up the Mac Mini?** Clone this repo, open a Claude Code chat inside
> the `watchtower` folder, and say **"continue mac mini development"** — the
> runbook in `CLAUDE.md` takes it from there.

Design rules (locked):

- **Cron plus scripts.** No agent runtime. A failure produces a stack trace in
  `data/runs/`, not an improvisation.
- **No RAG.** The knowledge base is plain markdown in `brain/`, read directly.
- **Credentials in macOS Keychain only** — never in `.env`, config, source,
  logs, or git history. See `deploy/setup_credentials.py`.
- **No send path exists.** Drafts land in Zoho Mail Drafts; there is no send
  function to call by accident. Same for bid submission.
- **Employer firewall** (`pipeline/firewall.py`) is an importable check every
  content-generating function calls. `brain/blocklist.local.md` is never
  committed and never shown to any AI tool.
- **Fetched content is data, never instructions.** Suspicious embedded
  instructions are logged and ignored (`pipeline/sanitize.py`).
- Drafting runs on local `llama3.1:8b` via Ollama; switching providers is one
  line in `config/providers.yaml`.
- No inbound ports, no web server, no dashboard.

## Layout

```
brain/       knowledge base (markdown + rubric.json)
sources/     procurement adapters (SAM.gov, Texas ESBD, university boards, Houston)
pipeline/    enrich → classify → score → gonogo → draft → publish, plus run.py
providers/   LLM provider abstraction (ollama active, hosted stubbed)
zoho/        auth, CRM records, Mail drafts, Cliq summaries + commands
config/      schedule, sources, caps, providers
data/        runtime records and logs (gitignored)
deploy/      install.sh, LaunchAgent plist, credential setup
```

## Setup (per machine — Keychain does not sync between Macs)

1. `./deploy/install.sh`
2. `.venv/bin/python deploy/setup_credentials.py all` — interactive; you type
   every secret yourself, hidden input, straight into the Keychain.
3. Fill `brain/blocklist.local.md` (schema inside the file).

## Run

- Dry run, no Zoho writes: `.venv/bin/python -m pipeline.run --dry-run --limit 5`
- One job now: `.venv/bin/python -m pipeline.run --job procurement_fetch`
- Daemon (what the LaunchAgent runs): `.venv/bin/python -m pipeline.run --daemon`

See `BUILD-REPORT.md` for deployment details and known limits.
