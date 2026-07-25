"""Entry point: one-shot jobs, dry runs, and the daemon.

    python -m pipeline.run --dry-run --limit 5      # zero Zoho writes, prints scores
    python -m pipeline.run --job procurement_fetch  # one live fetch cycle
    python -m pipeline.run --job apollo_enrich
    python -m pipeline.run --daemon                 # what the LaunchAgent runs

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
    anything else gets one reply naming the valid verbs. Never crashes the daemon."""
    from zoho.auth import ZohoAuth
    from zoho.cliq import MARKER, VALID_VERBS_REPLY, ZohoCliq, parse_command

    import logging as _logging
    plog = _logging.getLogger("cliq.poll")  # chatty 60s job: no per-poll run file

    try:
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
            plog.info("cliq command: %s %s", verb, arg or "")
            _dispatch_command(verb, arg, cliq)
        st = state.load()
        st["cliq_cursor"] = newest
        state.save(st)
    except Exception:
        _logging.getLogger("cliq.poll").exception("cliq poll failed (daemon continues)")


def _dispatch_command(verb: str, arg: str | None, cliq) -> None:
    if verb == "run":
        cliq.post("starting a procurement fetch cycle now.")
        summary = job_procurement_fetch()
        cliq.post(f"run finished: {json.dumps({k: summary.get(k) for k in ('new_records', 'go', 'no_go', 'needs_human', 'published')})}")
    elif verb == "status":
        st = state.load()
        caps_state = st.get("apollo_credit_ledger", {})
        cliq.post(f"status: paused={bool(st.get('paused'))}, "
                  f"apollo credits used this month={list(caps_state.values())[-1] if caps_state else 0}, "
                  f"drafts today={state.daily_count(st, 'drafts_created')}, "
                  f"sam calls today={state.daily_count(st, 'sam_api_calls')}")
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


def daemon() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    log, _ = new_run_logger("daemon")
    sched_cfg = config.schedule()
    scheduler = BlockingScheduler(
        timezone=sched_cfg.get("timezone", "America/Chicago"),
        job_defaults={"misfire_grace_time": 3600, "coalesce": True, "max_instances": 1})

    jobs = sched_cfg.get("jobs", {})
    if "procurement_fetch" in jobs:
        scheduler.add_job(job_procurement_fetch, "cron",
                          **jobs["procurement_fetch"]["cron"], id="procurement_fetch")
    if "apollo_enrich" in jobs:
        scheduler.add_job(job_apollo_enrich, "cron",
                          **jobs["apollo_enrich"]["cron"], id="apollo_enrich")
    if "cliq_poll" in jobs:
        scheduler.add_job(job_cliq_poll, "interval",
                          seconds=int(jobs["cliq_poll"].get("interval_seconds", 60)),
                          id="cliq_poll")
    log.info("daemon starting with jobs: %s (timezone %s)",
             list(jobs), sched_cfg.get("timezone"))
    scheduler.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.run")
    parser.add_argument("--dry-run", action="store_true",
                        help="no Zoho writes; prints scored items")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--job", choices=["procurement_fetch", "apollo_enrich", "cliq_poll"])
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args(argv)

    if args.daemon:
        daemon()
        return 0
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
