"""Apollo enrichment: pull ICP-matching prospects, spend as little as possible.

Credit economy (verified against docs.apollo.io 2026-07-24):
- POST /api/v1/mixed_people/api_search: 0 credits, master key required,
  returns people + organization but NO emails.
- GET  /api/v1/organizations/enrich: 1 credit per matched org (funding stage
  confirmation — search has no Series A/B filter).
- POST /api/v1/people/match: 1 credit (email reveal) — called at DRAFT time
  by draft_outreach, never here, so a scored-but-undrafted account costs at
  most 1 credit total.

Order of operations per candidate: firewall first (blocked domains are
dropped before anything is stored or any further API call is made), then the
30-day idempotency check, then the paid enrichment call.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

import requests

from pipeline import brain, storage
from pipeline.capgate import CapExceeded, CapGate
from pipeline.firewall import EmployerFirewall, get_firewall
from pipeline.models import Account

log = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "khavion-apollo-api-key"
KEYCHAIN_ACCOUNT = "khavion"

TITLE_PRIORITY = ["cto", "chief technology officer", "vp engineering",
                  "vp of engineering", "head of platform", "head of infrastructure",
                  "director of engineering"]


class ApolloError(Exception):
    pass


class ApolloClient:
    BASE = "https://api.apollo.io/api/v1"

    def __init__(self, api_key: str | None = None, timeout: int = 30):
        self._api_key = api_key
        self.timeout = timeout
        self._session = requests.Session()

    def _key(self) -> str:
        if not self._api_key:
            import keyring
            self._api_key = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        if not self._api_key:
            raise ApolloError(
                f"{KEYCHAIN_SERVICE} missing from Keychain; run deploy/setup_credentials.py apollo")
        return self._api_key

    def _request(self, method: str, url: str, **kwargs):
        headers = {"x-api-key": self._key(), "Content-Type": "application/json"}
        for attempt in range(4):
            resp = self._session.request(method, url, headers=headers,
                                         timeout=self.timeout, **kwargs)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                log.warning("apollo: 429 rate limited, backing off %ds", wait)
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                raise ApolloError(
                    "apollo: 403 - the key lacks access to this endpoint "
                    "(people search and usage stats require a MASTER key)")
            if resp.status_code >= 400:
                raise ApolloError(f"apollo: HTTP {resp.status_code}: {resp.text[:200]}")
            return resp
        raise ApolloError("apollo: still rate-limited after 4 attempts")

    def people_api_search(self, filters: dict, page: int = 1) -> dict:
        payload = dict(filters)
        payload["page"] = page
        return self._request("POST", f"{self.BASE}/mixed_people/api_search",
                             json=payload).json()

    def org_enrich(self, domain: str) -> dict:
        return self._request("GET", f"{self.BASE}/organizations/enrich",
                             params={"domain": domain}).json()

    def people_match(self, person_id: str | None = None, **identifiers) -> dict:
        payload = {"reveal_personal_emails": False, "reveal_phone_number": False,
                   **identifiers}
        if person_id:
            payload["id"] = person_id
        return self._request("POST", f"{self.BASE}/people/match", json=payload).json()

    def supported_technologies_csv(self) -> str:
        return self._request("GET", "https://api.apollo.io/v1/auth/supported_technologies_csv").text


def _best_person(people: list[dict]) -> dict | None:
    def rank(p):
        title = (p.get("title") or "").lower()
        for i, t in enumerate(TITLE_PRIORITY):
            if t in title:
                return i
        return len(TITLE_PRIORITY)
    matched = sorted(people, key=rank)
    return matched[0] if matched else None


def _org_of(person: dict) -> dict:
    return person.get("organization") or person.get("account") or {}


def _domain_of(org: dict) -> str | None:
    domain = org.get("primary_domain") or org.get("domain")
    if not domain and org.get("website_url"):
        domain = org["website_url"].split("//")[-1].split("/")[0]
    if domain:
        domain = domain.lower().removeprefix("www.")
    return domain


def _funding_trigger(enriched_org: dict) -> str | None:
    raw = (enriched_org.get("latest_funding_round_date")
           or enriched_org.get("latest_funding_date"))
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None
    if date.today() - when <= timedelta(days=180):
        stage = enriched_org.get("latest_funding_stage") or "funding round"
        return f"{stage} closed {when.isoformat()}"
    return None


def _recently_seen(domain: str, min_days: int) -> bool:
    existing = storage.load(storage.account_path(domain))
    if not existing:
        return False
    try:
        fetched = datetime.fromisoformat(existing["fetched_at"])
    except (KeyError, ValueError):
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched).days < min_days


def _disqualified(org: dict, keywords: list[str]) -> bool:
    haystack = " ".join(str(org.get(k, "")) for k in
                        ("short_description", "seo_description", "industry", "keywords")).lower()
    return any(k.lower() in haystack for k in keywords)


def run_enrichment(client: ApolloClient | None = None,
                   gate: CapGate | None = None,
                   firewall: EmployerFirewall | None = None,
                   pages: int = 1,
                   min_days_between: int | None = None,
                   dry_run: bool = False) -> dict:
    """One enrichment pass. Returns a summary dict for the run log."""
    client = client or ApolloClient()
    gate = gate or CapGate()
    firewall = firewall or get_firewall()
    filters = brain.icp_filters()
    disqualifiers = brain.icp_disqualifier_keywords()
    if min_days_between is None:
        from pipeline.config import caps
        min_days_between = int(caps().get("accounts", {}).get("min_days_between_touches", 30))

    summary = {"pages": 0, "people_seen": 0, "orgs_considered": 0,
               "firewall_dropped": 0, "recently_seen": 0, "disqualified": 0,
               "enriched": 0, "saved": 0, "credits_spent": 0, "saved_domains": []}

    # Search is free; collect candidate orgs with their best buyer.
    candidates: dict[str, dict] = {}
    for page in range(1, pages + 1):
        payload = client.people_api_search(filters, page=page)
        people = payload.get("people") or payload.get("contacts") or []
        summary["pages"] += 1
        summary["people_seen"] += len(people)
        by_org: dict[str, list[dict]] = {}
        for person in people:
            domain = _domain_of(_org_of(person))
            if domain:
                by_org.setdefault(domain, []).append(person)
        for domain, people_at_org in by_org.items():
            if domain not in candidates:
                candidates[domain] = {"people": people_at_org,
                                      "org": _org_of(people_at_org[0])}
        if not people:
            break

    for domain, bundle in candidates.items():
        summary["orgs_considered"] += 1

        # Firewall first: no storage, no further transmission, reason code only.
        code = firewall.check_domain(domain) or firewall.check_company(
            bundle["org"].get("name"))
        if code:
            summary["firewall_dropped"] += 1
            log.info("enrich: candidate dropped by employer firewall (%s)", code)
            continue

        if _recently_seen(domain, min_days_between):
            summary["recently_seen"] += 1
            continue

        if _disqualified(bundle["org"], disqualifiers):
            summary["disqualified"] += 1
            continue

        person = _best_person(bundle["people"])
        if person is None:
            continue

        if dry_run:
            summary["saved"] += 1
            continue

        # Paid step: 1 credit for org enrichment (funding-stage confirmation).
        try:
            gate.check_apollo_budget(planned_credits=1, run_spent=summary["credits_spent"])
        except CapExceeded as exc:
            log.error("enrich: %s", exc)
            summary["halted"] = str(exc)
            break
        enriched = (client.org_enrich(domain) or {}).get("organization") or {}
        gate.record_apollo_credits(1)
        summary["credits_spent"] += 1
        summary["enriched"] += 1

        org = {**bundle["org"], **enriched}
        triggers: dict[str, str] = {}
        funding = _funding_trigger(org)
        if funding:
            triggers["funding_recent"] = funding

        account = Account(
            domain=domain,
            company_name=org.get("name") or domain,
            apollo_org_id=str(org.get("id") or "") or None,
            employee_count=org.get("estimated_num_employees"),
            industry=org.get("industry"),
            locations=[str(org.get("country") or "")] if org.get("country") else [],
            technologies=[t for t in (org.get("technology_names") or [])][:40],
            funding_stage=org.get("latest_funding_stage"),
            latest_funding_date=None,
            triggers=triggers,
            buyer_name=person.get("name"),
            buyer_title=person.get("title"),
            buyer_seniority=person.get("seniority"),
            buyer_apollo_id=str(person.get("id") or "") or None,
            buyer_email=None,  # revealed only at draft time (1 credit)
            buyer_email_status=person.get("email_status"),
            raw={"org_keys": sorted(org.keys())[:60]},
        )
        storage.save(storage.account_path(domain), account.model_dump())
        summary["saved"] += 1
        summary["saved_domains"].append(domain)

    log.info("enrich summary: %s", summary)
    return summary
