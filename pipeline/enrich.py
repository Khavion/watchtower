"""Apollo enrichment: pull ICP-matching prospects, spend as little as possible.

Verified LIVE 2026-07-24 (the docs understate this): POST /mixed_people/api_search
(0 credits, master key) returns a heavily REDACTED shape - person carries only
id/title/first_name/has_email booleans, organization only its name. No domain,
no headcount, no email status. The full person + organization (including the
email) come from POST /people/match at 1 credit. Search filters do bind
(verified by probe: bogus technology uid -> 0 results), so every search hit
already satisfies employee range, US, and AWS/Kubernetes usage.

Flow, ordered for credit economy:
  1. api_search (free) -> rank people by buyer-title priority, one per company.
  2. Pre-credit drops: company-name firewall check, recently-seen-by-name.
  3. people/match (1 credit) -> full person + org + email in one call.
  4. Post-match checks: domain firewall (nothing stored/transmitted on a hit;
     the credit is already spent - unavoidable given the redacted search),
     30-day idempotency by domain, ICP disqualifiers, headcount confirmation.
  5. Save the account. Caps halt loudly at every paid step.
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

    def people_match(self, person_id: str | None = None, **identifiers) -> dict:
        payload = {"reveal_personal_emails": False, "reveal_phone_number": False,
                   **identifiers}
        if person_id:
            payload["id"] = person_id
        return self._request("POST", f"{self.BASE}/people/match", json=payload).json()

    def org_enrich(self, domain: str) -> dict:
        return self._request("GET", f"{self.BASE}/organizations/enrich",
                             params={"domain": domain}).json()

    def supported_technologies_csv(self) -> str:
        # NOTE: this CSV lists display names ("Amazon AWS"), not filter uids.
        # Filter-uid validity is checked empirically (bogus uid -> 0 results).
        return self._request("GET", "https://api.apollo.io/v1/auth/supported_technologies_csv").text


def _title_rank(title: str | None) -> int:
    lowered = (title or "").lower()
    for i, t in enumerate(TITLE_PRIORITY):
        if t in lowered:
            return i
    return len(TITLE_PRIORITY)


def _domain_of(org: dict) -> str | None:
    domain = org.get("primary_domain") or org.get("domain")
    if not domain and org.get("website_url"):
        domain = org["website_url"].split("//")[-1].split("/")[0]
    if domain:
        domain = domain.lower().removeprefix("www.")
    return domain


def _funding_trigger(org: dict) -> str | None:
    raw = org.get("latest_funding_round_date") or org.get("latest_funding_date")
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None
    if date.today() - when <= timedelta(days=180):
        stage = org.get("latest_funding_stage") or "funding round"
        return f"{stage} closed {when.isoformat()}"
    return None


def _recently_seen_domain(domain: str, min_days: int) -> bool:
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


def _recent_company_names(min_days: int) -> set[str]:
    """Company names of accounts touched within the window - the only pre-credit
    idempotency signal available, since search results carry no domain."""
    names = set()
    now = datetime.now(timezone.utc)
    for rec in storage.iter_records("accounts"):
        try:
            fetched = datetime.fromisoformat(rec["fetched_at"])
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if (now - fetched).days < min_days and rec.get("company_name"):
            names.add(rec["company_name"].lower())
    return names


def _disqualified(org: dict, keywords: list[str]) -> bool:
    haystack = " ".join(str(org.get(k, "")) for k in
                        ("short_description", "seo_description", "industry", "keywords")).lower()
    return any(k.lower() in haystack for k in keywords)


def run_enrichment(client: ApolloClient | None = None,
                   gate: CapGate | None = None,
                   firewall: EmployerFirewall | None = None,
                   pages: int = 1,
                   min_days_between: int | None = None,
                   dry_run: bool = False,
                   match_budget: int | None = None) -> dict:
    """One enrichment pass. Returns a summary dict for the run log."""
    client = client or ApolloClient()
    gate = gate or CapGate()
    firewall = firewall or get_firewall()
    filters = brain.icp_filters()
    disqualifiers = brain.icp_disqualifier_keywords()
    if min_days_between is None:
        from pipeline.config import caps
        min_days_between = int(caps().get("accounts", {}).get("min_days_between_touches", 30))

    summary = {"pages": 0, "people_seen": 0, "candidates": 0,
               "firewall_dropped": 0, "recently_seen": 0, "disqualified": 0,
               "out_of_icp": 0, "matched": 0, "saved": 0, "credits_spent": 0,
               "saved_domains": []}

    # Free discovery: rank buyers, one candidate per company name.
    people: list[dict] = []
    for page in range(1, pages + 1):
        payload = client.people_api_search(filters, page=page)
        batch = payload.get("people") or []
        summary["pages"] += 1
        summary["people_seen"] += len(batch)
        people.extend(batch)
        if not batch:
            break

    people.sort(key=lambda p: _title_rank(p.get("title")))
    recent_names = _recent_company_names(min_days_between)
    seen_names: set[str] = set()
    candidates: list[dict] = []
    for person in people:
        if _title_rank(person.get("title")) >= len(TITLE_PRIORITY):
            continue
        org_name = ((person.get("organization") or {}).get("name") or "").strip()
        if not org_name or org_name.lower() in seen_names:
            continue
        seen_names.add(org_name.lower())
        code = firewall.check_company(org_name)
        if code:
            summary["firewall_dropped"] += 1
            log.info("enrich: candidate dropped by employer firewall pre-match (%s)", code)
            continue
        if org_name.lower() in recent_names:
            summary["recently_seen"] += 1
            continue
        candidates.append(person)
    summary["candidates"] = len(candidates)

    if dry_run:
        summary["dry_run"] = True
        log.info("enrich (dry run) summary: %s", summary)
        return summary

    for person in candidates:
        if match_budget is not None and summary["matched"] >= match_budget:
            log.info("enrich: match budget (%d) reached for this run", match_budget)
            break
        # Paid step: 1 credit buys the full person + organization + email.
        try:
            gate.check_apollo_budget(planned_credits=1, run_spent=summary["credits_spent"])
        except CapExceeded as exc:
            log.error("enrich: %s", exc)
            summary["halted"] = str(exc)
            break
        matched = client.people_match(person_id=person.get("id")) or {}
        gate.record_apollo_credits(1)
        summary["credits_spent"] += 1
        summary["matched"] += 1

        full = matched.get("person") or {}
        org = full.get("organization") or {}
        domain = _domain_of(org)
        if not domain:
            continue

        code = firewall.check_domain(domain) or firewall.check_company(org.get("name"))
        if code:
            # Credit already spent (search hides domains); still: store nothing,
            # transmit nothing further, reason code only.
            summary["firewall_dropped"] += 1
            log.info("enrich: matched candidate dropped by employer firewall (%s)", code)
            continue
        if _recently_seen_domain(domain, min_days_between):
            summary["recently_seen"] += 1
            continue
        if _disqualified(org, disqualifiers):
            summary["disqualified"] += 1
            continue
        employees = org.get("estimated_num_employees")
        if employees is not None and not (20 <= int(employees) <= 200):
            summary["out_of_icp"] += 1
            continue

        technologies = [t for t in (org.get("technology_names") or [])][:40]
        if not technologies:
            # The search filter guaranteed AWS/Kubernetes usage; record that
            # provenance honestly rather than losing the signal.
            technologies = ["Amazon AWS (via search filter)", "Kubernetes (via search filter)"]

        triggers: dict[str, str] = {}
        funding = _funding_trigger(org)
        if funding:
            triggers["funding_recent"] = funding

        revenue = org.get("annual_revenue") or org.get("organization_revenue")
        account = Account(
            domain=domain,
            company_name=org.get("name") or domain,
            apollo_org_id=str(org.get("id") or "") or None,
            employee_count=int(employees) if employees is not None else None,
            industry=org.get("industry"),
            annual_revenue=float(revenue) if revenue else None,
            org_phone=(org.get("phone") or org.get("sanitized_phone")),
            city=org.get("city"),
            state=org.get("state"),
            linkedin_url=org.get("linkedin_url"),
            locations=[str(org.get("country") or "")] if org.get("country") else [],
            technologies=technologies,
            funding_stage=org.get("latest_funding_stage"),
            triggers=triggers,
            buyer_name=full.get("name") or person.get("first_name"),
            buyer_title=full.get("title") or person.get("title"),
            buyer_seniority=full.get("seniority"),
            buyer_apollo_id=str(full.get("id") or person.get("id") or "") or None,
            buyer_email=(full.get("email") if "not_unlocked" not in str(full.get("email")) else None),
            buyer_email_status=full.get("email_status"),
            raw={"org_keys": sorted(org.keys())[:60]},
        )
        storage.save(storage.account_path(domain), account.model_dump())
        summary["saved"] += 1
        summary["saved_domains"].append(domain)

    log.info("enrich summary: %s", summary)
    return summary
