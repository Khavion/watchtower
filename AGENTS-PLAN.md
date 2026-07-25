# The Khavion agent plan

Free. Local. On the Mac Mini. Nothing else.

Written 2026-07-25 after eight research studies. Every number here came from
testing or published measurement, not guesswork. Sources are in the research
notes; the short version is below in plain English.

---

## The answer to "can OpenClaw or Hermes do this?"

**Hermes: no, today.** It has no native Ollama support. It reaches Ollama only
through a compatibility endpoint that hangs and dies as soon as an agent has
tools — an open, unfixed bug on their own tracker, whose official workaround is
"use a paid cloud provider." Its own local guide asks for a 20 GB model and
24+ GB of RAM. Revisit if that bug is ever fixed.

**OpenClaw: yes, with conditions.** It has real Ollama support, a documented
small-model mode, per-agent model settings, its own scheduler, and it listens
only to the machine itself by default. Three catches, all handled below:

1. **Its shell access is wide open out of the box.** Default setting lets the
   AI run any command with no approval. That gets turned off before anything
   else is connected.
2. **Its Zoho Cliq add-on requires putting the Mini on the public internet.**
   That is exactly the configuration that got tens of thousands of OpenClaw
   users compromised. We do not use it. We already have a better way (below).
3. **"Only listens locally" is not the same as safe.** A patched flaw let a
   single bad link in a web browser take over local-only installs. So: the Mini
   stays a machine nobody browses on, and it gets updated.

---

## The shape of the system

One model, always loaded. Agents take turns using it.

Swapping models costs 3-10 seconds each time and risks pushing a 16 GB machine
into swap, where everything slows by 10x. So we don't swap. One model serves
every agent.

| What | Size | Why |
|---|---|---|
| `qwen3.5:9b` | 6.6 GB | The workhorse. Every agent uses it. |
| `nomic-embed-text` | 0.27 GB | Already installed. Search/recall when needed. |

Roughly 9 GB in memory once running, leaving comfortable room for macOS.

Why 9B and not something smaller or larger: on the standard tool-use benchmark
the 9B scores 0.661, the 4B scores 0.503 (24% worse), and the next size up
scores 0.685 — only 3.5% better, and it does not fit in 16 GB. 9B is the peak
of what this machine can do.

`gemma4:12b-it-qat` (7.2 GB) is the alternative. We test both for a week on real
work and keep the winner. We do not keep both.

### The turn-taking

A dispatcher wakes every few minutes, looks at a list of what's due, and runs
**exactly one** agent. A lock file makes a second one impossible. Schedules live
in a small database, so adding an agent later is one line.

macOS handles the Mini sleeping: anything due while it slept runs on wake.

---

## The agents

All five share the one model. They differ only in instructions and what they
are allowed to touch.

| Agent | When | What it does | What you see |
|---|---|---|---|
| **Lead finder** (built) | Weekdays 7am, 2pm | Finds solicitations and prospects, scores them | New rows in Zoho CRM |
| **Inbox triage** | Weekday mornings | Reads the Khavion inbox, sorts it, drafts replies | A short list in Cliq; drafts in Mail |
| **Marketing writer** | Sunday evening | Turns your week's notes into LinkedIn post drafts | Draft files + a Cliq message |
| **Proposal writer** | On demand | Turns a won call into an SOW draft from your templates | Draft file + a Cliq message |
| **Daily briefing** | 7am | One plain-English summary of everything | One Cliq message |

Nothing sends. Nothing posts. Every one of them produces something you approve.

---

## How you talk to it: Cliq, free, no exposure

Your Mini **calls out** to Zoho every minute and asks "any new commands?" It
never listens for incoming connections. No open ports, no domain name, no
tunnel, nothing for anyone to find or attack. This is how watchtower already
works, so it is proven.

Zoho's free Cliq plan allows 100 bots and 100 slash commands — far more than
needed, at no cost.

Commands available: `run`, `status`, `pause`, `resume`, `score <id>`,
`approve <id>`, `reject <id>`, `block <domain>`. More get added as agents land.

---

## Where OpenClaw fits (optional, later)

The research is clear that a 6.6 GB model is not reliable enough to run a
business process on its own — small models fumble multi-step tool use, and
OpenClaw's own docs recommend roughly $30,000 of hardware to do that
comfortably. So the split is:

- **The work stays deterministic.** Fixed steps, same order every time, AI used
  only where it writes text. This is why watchtower is reliable.
- **OpenClaw, if added, is only the conversation layer** — the thing that lets
  you type "what did this morning's run find?" in plain English instead of a
  fixed command.

That is a nice-to-have, not the system. It gets added last, after the agents
work, and only if the fixed commands feel limiting.

If it is added, these settings are non-negotiable: shell access denied,
messages allowed only from you, zero add-ons installed from their store (about
one in five were found to be malicious), no internet exposure, and a daily
restart because it leaks memory over long runs.

---

## Build order

1. **Fix what exists.** Swap in the better model, fix the context-window setting
   that is silently truncating long documents, add your real sent emails as
   writing examples, split drafting into two passes. Free, and it improves the
   drafts you already saw.
2. **The dispatcher.** Turn-taking, one-at-a-time, schedules in a database.
3. **Daily briefing agent.** Smallest, safest, immediately useful.
4. **Inbox triage agent.** Reads mail, sorts, drafts. Never sends.
5. **Marketing writer.** Drafts LinkedIn posts from your notes.
6. **Proposal writer.** Drafts SOWs from templates.
7. **OpenClaw as chat layer.** Optional, last, hardened.

---

## Two things that are not technical, but matter more than any of this

**Read your employment paperwork before Khavion markets publicly.** Texas
enforces non-competes, and Texas law says you owe your employer a duty of
loyalty whether or not you signed anything. Planning and building a business is
fine. Public marketing is the visible part. Most handbooks require disclosure
rather than forbidding side work, and disclosing in writing is the cheapest
protection there is. Not legal advice — but do not let a marketing agent go
live before you have checked.

**Automatic email sending is not available on the free plan.** Zoho removed the
ability for software to send mail from free accounts, and their usage policy
separately bans automated email. So the send button stays yours. That is not
caution, it is the shape of the free stack — and at your volume it costs you
about a minute a day.

---

## What this costs

$0/month. Everything above runs on hardware you own with models that are free
to download and free to use commercially.
