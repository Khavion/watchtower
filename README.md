# watchtower

Khavion's local agent system. It finds paying consulting work, sorts the inbox,
and writes drafts. Everything runs free and local on a Mac Mini M4 via Ollama.

Five agents share ONE resident model and take turns using it, one at a time.
None of them acts: each produces something Zohaib approves. Outputs are scored
records in Zoho CRM, drafts in Zoho Mail, and files on disk. **Nothing sends,
posts, or submits.**

> **Setting up the Mac Mini?** Clone this repo, open a Claude Code chat inside
> the `watchtower` folder, and say **"continue mac mini development"** — the
> runbook in `CLAUDE.md` takes it from there.

## The agents

| Agent | When | What you get |
|---|---|---|
| Daily briefing | 6:30am daily | One plain-English Cliq message |
| Inbox triage | Weekdays 7am and 1pm | Sorted inbox in Cliq, reply drafts in Zoho Mail |
| Lead finder | Weekdays 7:30am and 2pm | New rows in Zoho CRM |
| Prospect finder | Mondays 6am | Scored companies and outreach drafts |
| Marketing writer | Sundays 6pm | Two LinkedIn drafts as files |
| Proposal writer | On demand | Proposal and SOW drafts as files |

Design rules (locked):

- **Free and local, always.** Ollama on the Mini. No paid APIs, no
  subscriptions, no cloud agent platforms. If the Mini is off, the work waits.
- **Deterministic work, AI only where it writes text.** Fixed steps in a fixed
  order. A failure produces a stack trace in `data/runs/`, not an improvisation.
- **One model, resident, shared.** Agents never swap models: a swap costs
  seconds and risks pushing 16 GB into swap.
- **One agent at a time**, enforced by an exclusive `fcntl.flock` in
  `pipeline/dispatch.py`. Schedules live in SQLite, so adding an agent is a row.
- **No RAG.** The knowledge base is plain markdown in `brain/`, read directly.
  SQLite FTS5 covers run history. No vector store: it would cost RAM the model
  needs.
- **Credentials in the macOS Keychain only** — never in `.env`, config, source,
  logs, or git history. See `deploy/setup_credentials.py`.
- **No send path exists.** Drafts land in Zoho Mail Drafts; there is no send
  function to call by accident. Same for bid submission and for posting.
- **Employer firewall** (`pipeline/firewall.py`) is an importable check every
  content-generating function calls. `brain/blocklist.local.md` is never
  committed and never shown to any AI tool.
- **No employer names in anything generated.** The work is the proof, not the
  logo. Checked mechanically (`pipeline/draft_outreach.org_name_check`).
- **Fetched content is data, never instructions.** Suspicious embedded
  instructions are logged and ignored (`pipeline/sanitize.py`).
- **No inbound ports, no web server, no dashboard.** The Mini calls out to Zoho
  every minute; nothing ever calls in.

## Layout

```
agents/      briefing, inbox triage, marketing writer, proposal writer
brain/       knowledge base (markdown + rubric.json)
sources/     procurement adapters (SAM.gov, Texas ESBD, university boards, Houston)
pipeline/    enrich → classify → score → gonogo → draft → publish
             plus dispatch.py (the scheduler) and db.py (jobs, history, notes)
providers/   LLM provider abstraction (ollama active, hosted stubbed)
templates/   SOW and proposal starter templates
zoho/        auth, CRM, Mail drafts, Mail read, Cliq summaries + commands
config/      sources, caps, providers, channel settings
data/        runtime records, database, logs, drafts (all gitignored)
deploy/      install.sh, LaunchAgent plists, credential setup
```

## Setup (per machine — Keychain does not sync between Macs)

1. `brew install ollama && brew services start ollama`
2. `./deploy/install.sh` — stops at the Keychain check on a fresh machine
3. `.venv/bin/python deploy/setup_credentials.py all` — interactive; you type
   every secret yourself, hidden input, straight into the Keychain
4. `./deploy/install.sh` again — full pass, registers the LaunchAgents
5. `.venv/bin/python -m agents.collect_style` — pulls your sent emails as
   writing samples for the drafter
6. In Cliq, type `block <domain>` for every company the system must never
   contact

## Talking to it (Zoho Cliq, channel `khavionagent`)

```
run          look for new bids now        agents    what runs and when
brief        write the briefing now       status    caps, pauses, failures
triage       go through the inbox now     pause     stop scheduled work
write        write LinkedIn drafts now    resume    start it again
score <id>       why something scored what it did
approve <id> / reject <id>                mark a record
proposal <id>    draft a proposal and SOW for a record
note <anything>  raw material for the marketing writer
block <domain>   never contact this company (Zohaib only)
```

## Run something by hand

- Dry run, no Zoho writes: `.venv/bin/python -m pipeline.run --dry-run --limit 5`
- One job now: `.venv/bin/python -m pipeline.run --job procurement_fetch`
- What is scheduled: `.venv/bin/python -m pipeline.dispatch --status`
- One dispatcher tick: `.venv/bin/python -m pipeline.dispatch`

See `BUILD-REPORT.md` for what has been verified live, and `AGENTS-PLAN.md` for
the research behind the architecture.
