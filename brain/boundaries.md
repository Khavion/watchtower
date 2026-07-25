# Boundaries

What Khavion does **not** sell. Nothing in the pipeline drafts toward these;
`gonogo.py` and `score.py` treat a requirement for any of them as a
disqualifier, and the drafters refuse to propose them even when a prospect
asks-shaped signal appears.

## Not sold

- GPU provisioning or GPU cluster operations
- Model pre-training, or fine-tuning from scratch
- Low-level ML infrastructure (custom training stacks, kernel/driver work)
- Staff augmentation (bodies-for-hours in someone else's backlog)
- On-site work
- Hourly billing (offers are fixed-scope, calendar-duration priced)
- Anything requiring a compliance certification Khavion does not hold

## Certifications not held

Requirements naming any of these route to NO_GO (or NEEDS_HUMAN when ambiguous)
with the requirement quoted:

```yaml
unheld_certifications:
  - CMMC
  - "FedRAMP authorization"
  - "ISO 27001 certification"
  - "SOC 2 attestation"       # as a *required vendor certification*
  - "HITRUST"
  - "StateRAMP"
  - "CJIS"
  - "PCI DSS QSA"
# TODO(zohaib): confirm this list; add anything else you are asked for and
# do not hold (or remove anything you obtain later).
```

## The employer firewall

The firewall is not a policy paragraph; it is an importable check:
`pipeline.firewall` (see `pipeline/firewall.py`). Every content-generating
function calls it. Its contract:

1. Nothing in this system stores, references, or transmits the employer's
   customers, files, credentials, or performance figures.
2. The blocklist (`brain/blocklist.local.md`) is the machine-readable edge of
   the firewall: employer accounts and adjacents, matched by domain and parent
   company. A hit zeroes the score, blocks drafting, and never reaches publish.
3. The firewall reports **reason codes only**. Blocklist contents never appear
   in stdout, logs, prompts, LLM context, or any API payload.
4. Proof points referencing employer work carry explicit attribution
   (`proof.md`) and drafts must keep that attribution in-line.
5. If the blocklist file is missing, every run logs a loud warning and the
   production installer fails the deploy check.

```python
# The check every generator calls (signature, for reference):
from pipeline.firewall import employer_firewall
employer_firewall.check_domain("acme.com")        # -> Violation | None
employer_firewall.assert_clean(text, stage="draft_outreach")  # raises FirewallViolation
```
