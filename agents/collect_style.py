"""Collect Zohaib's own sent emails as style exemplars.

    .venv/bin/python -m agents.collect_style

Run once after credentials are in place, and again whenever his writing drifts.
This is the single biggest free quality gain available to the drafter: for a
structured format like email, a handful of real examples does more for voice
matching than any amount of prompt instruction, and model size barely matters.

What it writes: brain/style-exemplars.local.md, which is LOCAL ONLY. The
filename matches the `*.local*` rule in .gitignore, so it can never be
committed. It is his private correspondence and it stays on this machine.

What it filters out, deliberately:
- anything the employer firewall matches, because his sent mail may well discuss
  an employer account and that must never enter a model's context window;
- automated and one-line messages, which teach the model nothing;
- recipient addresses and phone numbers, which the drafter does not need.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys

from pipeline import brain
from pipeline.config import BRAIN_DIR
from pipeline.firewall import get_firewall
from pipeline.logutil import new_run_logger

log = logging.getLogger(__name__)

TARGET = BRAIN_DIR / brain.STYLE_EXEMPLARS_FILE
WANTED = 5
MIN_WORDS = 25
MAX_WORDS = 400

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"\+?\d[\d ().-]{8,}\d")
_AUTOMATED = re.compile(
    r"unsubscribe|no-?reply|automated message|do not reply|"
    r"view this email in your browser|calendar invitation",
    re.IGNORECASE)


def _usable(body: str) -> bool:
    words = len(body.split())
    if words < MIN_WORDS or words > MAX_WORDS:
        return False
    return not _AUTOMATED.search(body)


def _scrub(text: str) -> str:
    """Remove contact details. The drafter needs his rhythm, not his address book."""
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub("[phone]", text)
    return text.strip()


def collect(wanted: int = WANTED, log_: logging.Logger | None = None) -> int:
    logger = log_ or log
    from zoho.auth import ZohoAuth
    from zoho.mail_read import ZohoMailReadError, ZohoMailReader

    try:
        reader = ZohoMailReader(ZohoAuth())
        # Over-fetch: most sent mail is short replies and confirmations.
        candidates = reader.sent_messages_with_bodies(limit=max(20, wanted * 6))
    except ZohoMailReadError as exc:
        logger.error("collect_style: cannot read sent mail (%s)", exc)
        return 0

    firewall = get_firewall()
    kept: list[str] = []
    skipped_blocked = 0
    for msg in candidates:
        body = _scrub(msg.get("body", ""))
        if not _usable(body):
            continue
        if firewall.check_text(body) or firewall.check_text(msg.get("to", "")):
            # Reason codes only. The matched text is never logged.
            skipped_blocked += 1
            continue
        kept.append(body)
        if len(kept) >= wanted:
            break

    if not kept:
        logger.warning("collect_style: found no usable sent emails "
                       "(%d skipped by the employer firewall)", skipped_blocked)
        return 0

    TARGET.write_text(
        "# Style exemplars (LOCAL ONLY, never committed)\n\n"
        "Real emails Zohaib sent, used as voice examples by the drafter.\n"
        "Contact details removed. Anything the employer firewall matched was\n"
        "excluded and never entered a model context. Regenerate with:\n"
        "    .venv/bin/python -m agents.collect_style\n\n---\n"
        + "\n---\n".join(kept) + "\n")
    brain.clear_cache()
    logger.info("collect_style: wrote %d exemplars (%d skipped by the firewall)",
                len(kept), skipped_blocked)
    return len(kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents.collect_style")
    parser.add_argument("--count", type=int, default=WANTED)
    args = parser.parse_args(argv)

    logger, _ = new_run_logger("collect-style")
    count = collect(wanted=args.count, log_=logger)
    if count:
        print(f"Wrote {count} style exemplars to {TARGET.name} (local only).")
        return 0
    print("No usable sent emails were found. The drafter will fall back to the "
          "written voice rules.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
