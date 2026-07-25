"""Entry point: the lead-finding jobs, dry runs, and the Cliq poller.

    python -m pipeline.run --dry-run --limit 5      # zero Zoho writes, prints scores
    python -m pipeline.run --job procurement_fetch  # one live fetch cycle
    python -m pipeline.run --job apollo_enrich
    python -m pipeline.run --job cliq_poll          # one poll; what launchd runs

Scheduling lives in pipeline/dispatch.py and data/watchtower.db, not here and
not in a plist. This module provides jobs; the dispatcher decides when.

Dry-run performs ZERO Zoho writes structurally: no Zoho client is even
constructed. Scoring/gonogo/drafting chain onto completed fetches, not a
clock. Every run writes a dated log to data/runs/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime

from pipeline import brain, config, sanitize, state, storage
from pipeline.capgate import CapGate
from pipeline.classify import classify_solicitation
from pipeline.draft_bid_outline import draft_outline
from pipeline.draft_outreach import draft_touch_one
from pipeline.enrich import ApolloClient, run_enrichment
from pipeline.firewall import get_firewall
from pipeline.gonogo import run_gonogo
from pipeline.logutil import new_run_logger
from pipeline.models import GoNoGoVerdict
from pipeline.publish import PublishBlocked, publish_account, publish_solicitation
from pipeline.score import score_account, score_solicitation
from sources.base import PoliteSession, run_all
from sources.esbd import EsbdAdapter
from sources.houston_local import HoustonLocalAdapter
from sources.sam_gov import SamGovAdapter
from sources.university_boards import UniversityBoardsAdapter


def _paused() -> bool:
    return bool(state.load().get("paused"))


def _build_adapters(skip_keys: set[str]):
    cfg = config.sources()
    defaults = cfg.get("defaults", {})
    page_cache: dict = {}

    def session():
        return PoliteSession(
            user_agent=defaults.get("user_agent", "KhavionWatchtower/1.0"),
            min_interval=defaults.get("min_seconds_between_requests", 5),
            timeout=defaults.get("timeout_seconds", 30),
            max_retries=defaults.get("max_retries", 3),
            backoff_factor=defaults.get("backoff_factor", 2.0),
            page_cache=page_cache)

    return [
        EsbdAdapter(cfg, session=session(), skip_keys=skip_keys),
        SamGovAdapter(cfg, session=session(), skip_keys=skip_keys),
        UniversityBoardsAdapter(cfg, session=session(), skip_keys=skip_keys),
        HoustonLocalAdapter(cfg),
    ]


def _process_solicitation(record: dict, thresholds: dict, caps_cfg: dict,
                          dry_run: bool, services: dict, log) -> dict:
    """classify -> score -> gonogo -> draft -> publish, saving as it goes."""
    stages = {"classify": None, "score": None, "gonogo": None,
              "outline": None, "published": None}

    verdict_obj = None
    try:
        record["classification"] = classify_solicitation(record)
        stages["classify"] = record["classification"]["status"]
        relevant = record["classification"].get("relevant")

        if relevant is False and not dry_run:
            storage.save(storage.solicitation_path(record["dedupe_key"]), record)
            return record

        score = score_solicitation(
            record, min_deadline_days=int(caps_cfg.get("gonogo", {}).get("min_deadline_days", 7)))
        record["score"] = score.model_dump()
        stages["score"] = score.total

        if score.total >= thresholds.get("solicitation_gonogo_min", 50) or dry_run:
            verdict_obj = run_gonogo(
                record,
                weekly_capacity_hours=float(caps_cfg.get("capacity", {}).get("weekly_capacity_hours", 10)),
                min_deadline_days=int(caps_cfg.get("gonogo", {}).get("min_deadline_days", 7)))
            record["gonogo"] = verdict_obj.model_dump()
            stages["gonogo"] = verdict_obj.verdict

        if (not dry_run and verdict_obj is not None
                and verdict_obj.verdict == "GO" and relevant is not False):
            outline = draft_outline(record, verdict_obj)
            record["outline"] = outline
            stages["outline"] = outline["status"]

        if (not dry_run and record.get("score")
                and record["score"]["total"] >= thresholds.get("solicitation_gonogo_min", 50)):
            try:
                published = publish_solicitation(
                    record, record["score"], record.get("gonogo", {}),
                    record.get("outline"), crm=services.get("crm"))
                record["published"] = {"crm_id": published["crm_id"],
                                       "at": datetime.now().isoformat()}
                stages["published"] = published["crm_id"]
            except PublishBlocked as exc:
                record["published"] = {"blocked": exc.reason_code}
    except Exception:
        log.exception("processing failed for %s (record kept, run continues)",
                      record.get("dedupe_key"))
    if not dry_run:
        storage.save(storage.solicitation_path(record["dedupe_key"]), record)
    log.info("processed %s: %s", record.get("dedupe_key"), stages)
    return record


def _print_scored(records: list[dict]) -> None:
    for i, rec in enumerate(records, 1):
        score = rec.get("score") or {}
        print(f"\n[{i}] {rec.get('title', '(untitled)')[:90]}")
        print(f"    source={rec.get('source_id')}  key={rec.get('dedupe_key')}  "
              f"due={rec.get('due_date')}")
        cls = rec.get("classification") or {}
        print(f"    classify: {cls.get('status')} relevant={cls.get('relevant')} "
              f"({cls.get('reason', '')[:70]})")
        if cls.get("relevant") is False:
            # Dry-run scores everything so the rubric can be inspected, but a
            # live run stops at the classifier. Say so, or the GO printed below
            # reads as if this were going to be pursued.
            print("      (a live run would stop here: scored below only so you "
                  "can check the rubric)")
        print(f"    score: {score.get('total')} (rubric {score.get('rubric_version')})"
              f"  hard_fails={score.get('hard_fails')}")
        for name, crit in (score.get("criteria") or {}).items():
            print(f"      - {name:<18} {crit['criterion_score']:>3}/100  "
                  f"weight {crit['weight']:>2}  -> {crit['weighted']}")
        gng = rec.get("gonogo") or {}
        if gng:
            print(f"    gonogo: {gng.get('verdict')}  "
                  f"({'; '.join(gng.get('reasons', []))[:110]})")


def job_procurement_fetch(dry_run: bool = False, limit: int | None = None) -> dict:
    log, log_path = new_run_logger("procurement")
    if _paused() and not dry_run:
        log.warning("run is PAUSED (cliq `resume` to continue); skipping fetch")
        return {"paused": True}
    from pipeline import firewall as _fw
    _fw.reset()  # long-lived daemon: pick up blocklist rows added since last run
    config.ensure_data_dirs()
    thresholds = brain.rubric()["thresholds"]
    caps_cfg = config.caps()

    skip = storage.known_solicitation_keys()
    results, errors = run_all(_build_adapters(skip), log)

    fresh: list[dict] = []
    for source_id, sols in results.items():
        for sol in sols:
            record = sol.model_dump()
            findings = sanitize.scan(f"{record.get('title', '')}\n{record.get('description', '')}",
                                     context=record.get("dedupe_key", source_id))
            record["suspicious_content"] = bool(findings)
            if record["dedupe_key"] not in skip:
                fresh.append(record)

    if limit is not None:
        fresh = fresh[:limit]

    services: dict = {}
    if not dry_run:
        from zoho.auth import ZohoAuth
        from zoho.cliq import ZohoCliq
        from zoho.crm import ZohoCRM
        auth = ZohoAuth()
        services = {"crm": ZohoCRM(auth),
                    "cliq": ZohoCliq(auth, config.schedule().get("cliq", {}).get(
                        "channel_unique_name", "khavionagent"))}

    processed = [_process_solicitation(r, thresholds, caps_cfg, dry_run, services, log)
                 for r in fresh]

    summary = {
        "job": "procurement_fetch", "dry_run": dry_run,
        "fetched": {k: len(v) for k, v in results.items()},
        "errors": {k: v.splitlines()[-1] for k, v in errors.items()},
        "new_records": len(processed),
        "published": sum(1 for r in processed if (r.get("published") or {}).get("crm_id")),
        "go": sum(1 for r in processed if (r.get("gonogo") or {}).get("verdict") == "GO"),
        "no_go": sum(1 for r in processed if (r.get("gonogo") or {}).get("verdict") == "NO_GO"),
        "needs_human": sum(1 for r in processed
                           if (r.get("gonogo") or {}).get("verdict") == "NEEDS_HUMAN"),
        "log": str(log_path),
    }
    log.info("procurement summary: %s", json.dumps(summary, default=str))

    if dry_run:
        _print_scored(processed)
        print(f"\ndry run complete: {len(processed)} records, zero Zoho writes "
              f"(no Zoho client constructed). Log: {log_path}")
    elif services.get("cliq"):
        try:
            services["cliq"].post(
                f"procurement run: {summary['new_records']} new "
                f"(GO {summary['go']} / NO_GO {summary['no_go']} / "
                f"NEEDS_HUMAN {summary['needs_human']}), "
                f"{summary['published']} published to CRM. "
                f"Sources: {summary['fetched']}. Errors: {list(summary['errors']) or 'none'}")
        except Exception:
            log.exception("cliq summary post failed (run itself succeeded)")
    return summary


def job_apollo_enrich(dry_run: bool = False, limit: int | None = None) -> dict:
    log, log_path = new_run_logger("apollo-enrich")
    if _paused() and not dry_run:
        log.warning("run is PAUSED; skipping enrichment")
        return {"paused": True}
    from pipeline import firewall as _fw
    _fw.reset()
    config.ensure_data_dirs()
    thresholds = brain.rubric()["thresholds"]

    client = None if dry_run else ApolloClient()
    gate = CapGate()
    summary = run_enrichment(client=client, gate=gate, dry_run=dry_run) if not dry_run \
        else {"dry_run": True, "saved_domains": []}

    services: dict = {}
    if not dry_run:
        from zoho.auth import ZohoAuth
        from zoho.crm import ZohoCRM
        from zoho.mail import ZohoMail
        auth = ZohoAuth()
        services = {"crm": ZohoCRM(auth), "mail": ZohoMail(auth)}

    drafted = 0
    for domain in (summary.get("saved_domains") or [])[:limit]:
        account = storage.load(storage.account_path(domain)) or {}
        score = score_account(account)
        account["score"] = score.model_dump()
        draft: dict = {"status": "BELOW_THRESHOLD"}
        if score.total >= thresholds.get("account_draft_min", 60):
            draft = draft_touch_one(account, gate=gate, apollo_client=client)
            account["draft"] = {k: v for k, v in draft.items() if k != "body"}
            if draft.get("status") in ("DRAFTED", "NO_EMAIL"):
                drafted += 1
        # Every scored account lands in the CRM: the CRM is Zohaib's single
        # window into what the agent found, drafted or not.
        try:
            publish_account(account, account["score"], draft,
                            crm=services.get("crm"), mail=services.get("mail"))
        except PublishBlocked:
            pass
        storage.save(storage.account_path(domain), account)

    summary["drafted"] = drafted
    summary["log"] = str(log_path)
    log.info("enrichment summary: %s", json.dumps(summary, default=str))
    return summary


def job_cliq_poll() -> None:
    """Poll the channel for commands. Strict allowlist; own messages ignored;
    anything else gets one reply naming the valid verbs. Never raises.

    Holds the CLIQ lock, not the agent lock, so chat stays responsive while a
    long agent is running. Commands that start work enqueue a job for the
    dispatcher rather than running it here, which is what keeps the
    one-agent-at-a-time guarantee true.
    """
    import logging as _logging

    from pipeline.dispatch import CLIQ_LOCK, Busy, exclusive_lock
    from zoho.auth import ZohoAuth
    from zoho.cliq import MARKER, VALID_VERBS_REPLY, ZohoCliq, is_owner_only, parse_command

    plog = _logging.getLogger("cliq.poll")  # chatty 60s job: no per-poll run file

    try:
        with exclusive_lock(CLIQ_LOCK):
            cliq = ZohoCliq(ZohoAuth(), config.schedule().get("cliq", {}).get(
                "channel_unique_name", "khavionagent"))
            st = state.load()
            cursor = int(st.get("cliq_cursor") or (time.time() - 120) * 1000)
            messages = cliq.fetch_messages(cursor)
            if not messages:
                return
            newest = cursor
            for msg in messages:
                newest = max(newest, msg["time"] + 1)
                text = msg["text"]
                if text.strip().startswith(MARKER):
                    continue  # our own output
                sanitize.scan(text, context="cliq message")
                command = parse_command(text)
                if command is None:
                    plog.warning("cliq: non-command message ignored; replying with verbs")
                    cliq.post(VALID_VERBS_REPLY)
                    continue
                verb, arg = command
                if is_owner_only(verb) and not _is_owner(cliq, msg, st):
                    plog.warning("cliq: refused owner-only verb %r from another user", verb)
                    cliq.post("that command is Zohaib's only. Nothing was changed.")
                    continue
                # The argument is deliberately not logged: `note` text is his,
                # and `block` domains must never reach a log file.
                plog.info("cliq command: %s", verb)
                _dispatch_command(verb, arg, cliq)
            st = state.load()
            st["cliq_cursor"] = newest
            state.save(st)
    except Busy:
        return  # a previous poll is still running; the next tick is 60s away
    except Exception:
        _logging.getLogger("cliq.poll").exception("cliq poll failed (next tick retries)")


def _is_owner(cliq, msg: dict, st: dict) -> bool:
    """Owner-only verbs fail closed. Identity comes from Cliq's own payload and
    from the OAuth token's owner, never from anything typed in a message."""
    owner = st.get("cliq_owner_id")
    if not owner:
        owner = cliq.owner_id()
        if owner:
            st["cliq_owner_id"] = owner
            state.save(st)
    if not owner:
        return False
    return str(msg.get("sender_id") or "") == str(owner)


# Commands that start work never run it inline: they enqueue a job and the
# dispatcher runs it under the single agent lock. That is what keeps "exactly
# one agent at a time" true even when Zohaib types `run` mid-morning.
ENQUEUE_VERBS = {
    "run": ("procurement_fetch", "looking for new bids now. I will post what I find."),
    "brief": ("daily_briefing", "writing your briefing now."),
    "triage": ("inbox_triage", "going through the inbox now."),
    "write": ("marketing_writer", "writing LinkedIn drafts now."),
}


def _dispatch_command(verb: str, arg: str | None, cliq) -> None:
    from pipeline import db

    if verb in ENQUEUE_VERBS:
        job_name, ack = ENQUEUE_VERBS[verb]
        conn = db.connect()
        if db.enqueue(conn, job_name):
            cliq.post(f"{ack} It starts within a minute, or as soon as whatever "
                      f"is running now finishes.")
        else:
            cliq.post("that job is not registered on this machine yet.")
    elif verb == "proposal":
        conn = db.connect()
        # The record id rides in last_summary, which the agent reads back. Kept
        # deliberately simple: there is exactly one proposal request in flight.
        conn.execute("UPDATE jobs SET last_summary = ? WHERE name = 'proposal_writer'",
                     (arg,))
        conn.commit()
        if db.enqueue(conn, "proposal_writer"):
            cliq.post(f"writing a proposal and SOW draft for {arg}. "
                      f"They will land as files, nothing gets sent.")
        else:
            cliq.post("the proposal writer is not registered on this machine yet.")
    elif verb == "note":
        conn = db.connect()
        db.add_note(conn, arg or "")
        cliq.post("noted. I will use it in your next batch of LinkedIn drafts.")
    elif verb == "agents":
        conn = db.connect()
        lines = ["what runs on its own:"]
        for row in conn.execute("SELECT * FROM jobs ORDER BY name"):
            when = (row["next_due_at"] or "on request")[:16].replace("T", " ")
            state_word = "" if row["enabled"] else " (off)"
            lines.append(f"- {row['description'] or row['name']}: next {when}{state_word}")
        cliq.post("\n".join(lines))
    elif verb == "status":
        st = state.load()
        conn = db.connect()
        caps_state = st.get("apollo_credit_ledger", {})
        failures = [r["job_name"] for r in db.recent_runs(conn, 24)
                    if r["status"] == "FAILED"]
        cliq.post(f"paused: {'yes' if st.get('paused') else 'no'}. "
                  f"Prospect credits used this month: "
                  f"{list(caps_state.values())[-1] if caps_state else 0}. "
                  f"Drafts written today: {state.daily_count(st, 'drafts_created')}. "
                  f"Government searches today: {state.daily_count(st, 'sam_api_calls')}. "
                  f"Anything broken in the last day: "
                  f"{', '.join(sorted(set(failures))) if failures else 'no'}.")
    elif verb == "pause":
        st = state.load(); st["paused"] = True; state.save(st)
        cliq.post("paused. scheduled fetch/enrich jobs will skip until `resume`.")
    elif verb == "resume":
        st = state.load(); st["paused"] = False; state.save(st)
        cliq.post("resumed.")
    elif verb == "block":
        from pipeline import firewall as fw
        domain = (arg or "").lower().strip()
        if not re.match(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", domain):
            cliq.post("that does not look like a domain (expected e.g. example.com); "
                      "nothing was blocked.")
            return
        fw.append_block(domain)
        # Deliberately no echo of the domain: blocklist contents stay out of
        # logs and generated messages.
        cliq.post("added to the local blocklist (EMPLOYER_ACCOUNT). That company "
                  "will never be scored, drafted, or stored again on this machine.")
    elif verb in ("score", "approve", "reject"):
        record = storage.load(storage.solicitation_path(arg))
        if record is None:
            for rec in storage.iter_records("solicitations"):
                if rec.get("dedupe_key", "").endswith(arg) or rec.get("native_id") == arg:
                    record = rec
                    break
        if record is None:
            cliq.post(f"no record found for id {arg!r}")
            return
        if verb == "score":
            score = record.get("score") or {}
            lines = [f"{record.get('dedupe_key')}: total {score.get('total')} "
                     f"(rubric {score.get('rubric_version')})"]
            for name, crit in (score.get("criteria") or {}).items():
                lines.append(f"{name}: {crit.get('criterion_score')}/100 x{crit.get('weight')}")
            verdict = (record.get("gonogo") or {}).get("verdict")
            lines.append(f"gonogo: {verdict}")
            cliq.post(" | ".join(lines))
        else:
            record["review"] = {"decision": verb + "d",
                                "at": datetime.now().isoformat()}
            storage.save(storage.solicitation_path(record["dedupe_key"]), record)
            cliq.post(f"{record.get('dedupe_key')} marked {verb}d. "
                      f"(Email sending stays manual in Zoho Mail.)")


# The long-lived APScheduler daemon was retired on 2026-07-25 and replaced by
# pipeline/dispatch.py. Three reasons: a permanently resident Python process
# holds memory this machine would rather give the model; its schedule lived in a
# file rather than a table, so adding an agent meant editing config and
# restarting; and its per-job guard could not stop two DIFFERENT agents running
# at once, which is the collision that actually matters on 16 GB.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.run")
    parser.add_argument("--dry-run", action="store_true",
                        help="no Zoho writes; prints scored items")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--job", choices=["procurement_fetch", "apollo_enrich", "cliq_poll"])
    args = parser.parse_args(argv)

    if args.job == "apollo_enrich":
        job_apollo_enrich(dry_run=args.dry_run, limit=args.limit)
        return 0
    if args.job == "cliq_poll":
        job_cliq_poll()
        return 0
    job_procurement_fetch(dry_run=args.dry_run, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
