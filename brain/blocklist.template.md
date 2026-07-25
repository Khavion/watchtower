# Blocklist (LOCAL ONLY) — template

**This file's live copy (`blocklist.local.md`) is never committed
(`.gitignore: *.local*`) and its contents are never pasted into any AI tool,
prompt, log, API call, or terminal output.** Code reads it and reports
pass/fail with reason codes only.

`deploy/install.sh` copies this template to `brain/blocklist.local.md` when
missing. Only Zohaib fills the live copy, by hand, on each machine (it does
not sync). Populating it requires knowledge of employer accounts, which must
never enter an AI context window.

TODO(zohaib): fill the table in `blocklist.local.md` on this machine.

## Schema

One row per blocked entity. `domain` is the primary key (exact or suffix
match); `parent_company` catches subsidiaries whose domain differs.

| domain | parent_company | reason_code | date_added |
|---|---|---|---|
| example.com | Example Corp | EMPLOYER_ACCOUNT | 2026-07-24 |

## Reason codes

- `EMPLOYER_ACCOUNT` — a current-employer customer or prospect
- `EMPLOYER_ADJACENT` — partner, vendor, or entity close enough to create a conflict
- `SUBSIDIARY_OF_BLOCKED` — child company of a blocked parent
- `PERSONAL` — personal reasons, no explanation required

## Rules the code enforces

1. A domain match zeroes the score (`rubric.json` hard_fail: `blocklist_hit`),
   produces no draft, and never reaches `publish.py`.
2. The match reason is logged as the reason code only — never the row content.
3. Matching is case-insensitive on registrable domain (`foo.example.com`
   matches `example.com`) and substring on `parent_company`.
4. If the live file is missing, every run logs a loud warning and
   `install.sh` recreates it from this template.
