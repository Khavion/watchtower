#!/usr/bin/env python3
"""Phase 1 credential setup for Khavion watchtower.

Run this yourself, in your own Terminal:

    .venv/bin/python deploy/setup_credentials.py all
    .venv/bin/python deploy/setup_credentials.py apollo | sam | zoho | verify

Every secret is entered through a hidden interactive prompt (getpass): it never
appears on screen, in shell history, in argv/`ps`, in any log, or in any file.
Values go straight into the macOS login Keychain via the `keyring` library.

Why keyring and not the `security` CLI: `security add-generic-password -w <value>`
exposes the value in `ps` argv. The safe CLI form (`man security`, verified
2026-07-24: "-w password  Specify password to be added. Put at end of command to
be prompted (recommended)") double-prompts with hidden input and is the manual
fallback:

    security add-generic-password -U -a khavion -s <service-name> -w

Creating items via this script's python has a second benefit: the Keychain
item's ACL trusts the same python binary the runtime uses, so the LaunchAgent
never hits an unattended "Allow?" dialog.

HARD RULE: this script can only touch the six services in ALLOWED_SERVICES.
The pre-existing entries `khavion-google-client-secret` and
`khavion-site-zoho-refresh` are never read, written, or deleted.

API facts referenced below were verified against official docs on 2026-07-24.
"""

import getpass
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import keyring
import requests

ACCOUNT = "khavion"

ALLOWED_SERVICES = frozenset({
    "khavion-apollo-api-key",
    "khavion-sam-api-key",
    "khavion-zoho-client-id",
    "khavion-zoho-client-secret",
    "khavion-zoho-refresh-token",
    "khavion-zoho-region",
})

# Never touched, in any direction. Guarded in _store/_read.
PROTECTED_SERVICES = frozenset({
    "khavion-google-client-secret",
    "khavion-site-zoho-refresh",
})

# Region -> endpoints (Zoho multi-DC, verified 2026-07-24).
ZOHO_REGIONS = {
    "US": {"accounts": "https://accounts.zoho.com",
           "mail": "https://mail.zoho.com",
           "cliq": "https://cliq.zoho.com",
           "crm_fallback": "https://www.zohoapis.com"},
    "EU": {"accounts": "https://accounts.zoho.eu",
           "mail": "https://mail.zoho.eu",
           "cliq": "https://cliq.zoho.eu",
           "crm_fallback": "https://www.zohoapis.eu"},
    "IN": {"accounts": "https://accounts.zoho.in",
           "mail": "https://mail.zoho.in",
           "cliq": "https://cliq.zoho.in",
           "crm_fallback": "https://www.zohoapis.in"},
    "AU": {"accounts": "https://accounts.zoho.com.au",
           "mail": "https://mail.zoho.com.au",
           "cliq": "https://cliq.zoho.com.au",
           "crm_fallback": "https://www.zohoapis.com.au"},
    "CA": {"accounts": "https://accounts.zohocloud.ca",
           "mail": "https://mail.zohocloud.ca",
           "cliq": "https://cliq.zohocloud.ca",
           "crm_fallback": "https://www.zohoapis.ca"},
}

# Single grant-token scope line (exact strings verified 2026-07-24).
# 2026-07-25: ZohoMail.messages.READ + ZohoMail.folders.READ added at Zohaib's
# request so the inbox-triage agent can READ mail. There is still no send scope
# and no send code path anywhere in this repo; triage drafts replies only.
ZOHO_SCOPES = ("ZohoCRM.modules.ALL,ZohoCRM.settings.fields.READ,"
               "ZohoMail.accounts.READ,ZohoMail.messages.CREATE,"
               "ZohoMail.messages.READ,ZohoMail.folders.READ,"
               "ZohoCliq.Webhooks.CREATE,ZohoCliq.Channels.READ,"
               "ZohoCliq.Messages.READ")

CLIQ_CHANNEL = "khavionagent"
REPO_ROOT = Path(__file__).resolve().parent.parent
CAPS_FILE = REPO_ROOT / "config" / "caps.yaml"
TIMEOUT = 30


def _guard(service: str) -> None:
    if service in PROTECTED_SERVICES:
        raise SystemExit(f"REFUSING to touch protected Keychain entry: {service}")
    if service not in ALLOWED_SERVICES:
        raise SystemExit(f"REFUSING to touch non-allowlisted Keychain entry: {service}")


def _store(service: str, value: str) -> None:
    _guard(service)
    keyring.set_password(service, ACCOUNT, value)


def _read(service: str):
    _guard(service)
    return keyring.get_password(service, ACCOUNT)


def _masked(value: str) -> str:
    if not value:
        return "(empty)"
    tail = value[-4:] if len(value) >= 8 else ""
    return f"len={len(value)} ****{tail}"


def _secret(label: str) -> str:
    value = getpass.getpass(f"  {label} (hidden input): ").strip()
    if not value:
        raise SystemExit("Empty value entered; aborting this step. Re-run when ready.")
    return value


def _banner(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(1, 60 - len(title)))


def setup_apollo() -> None:
    _banner("Apollo")
    print("Console: app.apollo.io -> Settings -> Integrations -> API Keys")
    print("Create a key and toggle 'Set as master key' (people search + usage stats require it).")
    key = _secret("Apollo master API key")

    r = requests.get("https://api.apollo.io/v1/auth/health",
                     headers={"x-api-key": key}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SystemExit(f"Apollo health check failed (HTTP {r.status_code}). "
                         "Key not stored. Check the key and re-run: setup_credentials.py apollo")
    print("  health check: OK")

    usage_note = "unavailable"
    u = requests.post("https://api.apollo.io/api/v1/usage_stats/api_usage_stats",
                      headers={"x-api-key": key, "Content-Type": "application/json"},
                      json={}, timeout=TIMEOUT)
    if u.status_code == 403:
        print("  WARNING: usage_stats returned 403 -> this key is NOT a master key.")
        print("  People search will fail. Regenerate as master key and re-run this step.")
    elif u.status_code == 200:
        try:
            payload = u.json()
            keys = list(payload.keys()) if isinstance(payload, dict) else []
            print(f"  usage stats: OK (top-level fields: {keys[:12]})")
            credit_bits = {k: v for k, v in payload.items()
                           if isinstance(payload, dict) and "credit" in k.lower()}
            if credit_bits:
                print("  credit-related fields reported by the API:")
                print("  " + json.dumps(credit_bits, indent=2)[:1200])
                usage_note = "shown above"
        except ValueError:
            print("  usage stats: response was not JSON")
    else:
        print(f"  usage stats: HTTP {u.status_code} (continuing)")

    _store("khavion-apollo-api-key", key)
    print(f"  stored khavion-apollo-api-key ({_masked(key)})")

    print(f"\n  Monthly cap is set to 50% of your current credit balance ({usage_note}).")
    print("  If the API output above shows no clear remaining balance, read it from")
    print("  Settings -> Billing & credits -> Credit usage.")
    raw = input("  Enter your current available credit balance (integer, or blank to skip): ").strip()
    if raw:
        try:
            balance = int(raw.replace(",", ""))
        except ValueError:
            print("  Not an integer; skipping cap update. Edit config/caps.yaml manually.")
            return
        cap = balance // 2
        text = CAPS_FILE.read_text()
        new = re.sub(r"(monthly_credit_cap:)\s*\d+", rf"\g<1> {cap}", text, count=1)
        CAPS_FILE.write_text(new)
        print(f"  caps.yaml: apollo.monthly_credit_cap = {cap} (50% of {balance})")
    else:
        print("  Skipped. Enrichment stays blocked until monthly_credit_cap > 0 in config/caps.yaml.")


def setup_sam() -> None:
    _banner("SAM.gov")
    print("Key: sam.gov -> sign in -> Account Details -> re-enter password -> API key shown.")
    key = _secret("SAM.gov public API key")

    today = date.today()
    params = {
        "api_key": key,
        "limit": 1,
        "postedFrom": (today - timedelta(days=7)).strftime("%m/%d/%Y"),
        "postedTo": today.strftime("%m/%d/%Y"),
        "ptype": "r",
        "ncode": "541512",
    }
    r = requests.get("https://api.sam.gov/opportunities/v2/search",
                     params=params, timeout=TIMEOUT)
    if r.status_code == 200:
        try:
            total = r.json().get("totalRecords")
            print(f"  verification search: OK (Sources Sought, NAICS 541512, last 7 days: {total} records)")
        except ValueError:
            print("  verification search: HTTP 200 but non-JSON body (continuing)")
    elif r.status_code == 429:
        print("  HTTP 429: daily quota exhausted (basic keys allow 10 calls/day).")
        print("  The key format was accepted; storing it. Re-verify tomorrow.")
    else:
        raise SystemExit(f"SAM.gov verification failed (HTTP {r.status_code}): {r.text[:300]}\n"
                         "Key not stored. Re-run: setup_credentials.py sam")

    _store("khavion-sam-api-key", key)
    print(f"  stored khavion-sam-api-key ({_masked(key)})")
    print("  NOTE: basic personal keys are limited to 10 requests/day.")
    print("  TODO(zohaib): associate your entity with your sam.gov profile -> 1,000/day.")


def setup_zoho() -> None:
    _banner("Zoho (self-client OAuth)")
    print("Console: api-console.zoho.com -> Self Client -> Client Secret tab has ID+secret.")
    print("Then Generate Code tab -> paste EXACTLY this scope line, duration 10 minutes:")
    print(f"\n  {ZOHO_SCOPES}\n")
    print("The grant code is one-shot and expires in minutes: generate it LAST,")
    print("then finish these prompts immediately.")

    region = (input(f"  Zoho region {sorted(ZOHO_REGIONS)} [US]: ").strip().upper() or "US")
    if region not in ZOHO_REGIONS:
        raise SystemExit(f"Unknown region {region!r}. Re-run: setup_credentials.py zoho")
    ep = ZOHO_REGIONS[region]

    client_id = _secret("Zoho client ID")
    client_secret = _secret("Zoho client secret")
    grant_code = _secret("Zoho grant code (from Generate Code)")

    r = requests.post(f"{ep['accounts']}/oauth/v2/token", data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": grant_code,
    }, timeout=TIMEOUT)
    try:
        tok = r.json()
    except ValueError:
        raise SystemExit(f"Token exchange returned non-JSON (HTTP {r.status_code}). Nothing stored.")

    if "error" in tok:
        err = tok["error"]
        hints = {
            "invalid_code": "Grant code expired or already used -> generate a fresh code and re-run.",
            "invalid_client": "Client ID/secret wrong, or your account lives in a different "
                              "datacenter than the one selected.",
        }
        raise SystemExit(f"Token exchange failed: {err}. {hints.get(err, '')} Nothing stored.")

    refresh_token = tok.get("refresh_token")
    access_token = tok.get("access_token")  # held in memory only, discarded on exit
    api_domain = tok.get("api_domain") or ep["crm_fallback"]
    if not refresh_token:
        raise SystemExit("No refresh_token in response (got access token only). This usually means "
                         "the code was not generated from a Self Client. Nothing stored.")
    print(f"  token exchange: OK (api_domain {api_domain})")

    zoho_hdr = {"Authorization": f"Zoho-oauthtoken {access_token}"}   # CRM + Mail
    bearer_hdr = {"Authorization": f"Bearer {access_token}"}          # Cliq

    # Verify with a records read: the pipeline uses ZohoCRM.modules.* only.
    # (/crm/v8/org would need ZohoCRM.org.READ, which we deliberately don't request.)
    crm = requests.get(f"{api_domain}/crm/v8/Leads",
                       params={"fields": "Email", "per_page": 1},
                       headers=zoho_hdr, timeout=TIMEOUT)
    if crm.status_code in (200, 204):
        print("  CRM: OK (Leads module readable; 204 just means no records yet)")
    else:
        print(f"  CRM: HTTP {crm.status_code} — check ZohoCRM scopes ({crm.text[:150]})")

    mail = requests.get(f"{ep['mail']}/api/accounts", headers=zoho_hdr, timeout=TIMEOUT)
    account_id = None
    if mail.status_code == 200:
        try:
            acct = mail.json().get("data", [{}])[0]
            account_id = acct.get("accountId")
            print(f"  Mail: OK (accountId {account_id}, "
                  f"primary {acct.get('primaryEmailAddress')})")
        except (ValueError, IndexError, AttributeError):
            print("  Mail: HTTP 200")
    else:
        print(f"  Mail: HTTP {mail.status_code} — check ZohoMail scopes ({mail.text[:150]})")

    # Mail READ is a new scope (2026-07-25). Verify it here so a missing scope is
    # caught now, while the console is still open, and not at 7am by the triage agent.
    if account_id:
        folders = requests.get(f"{ep['mail']}/api/accounts/{account_id}/folders",
                               headers=zoho_hdr, timeout=TIMEOUT)
        if folders.status_code == 200:
            try:
                names = [f.get("folderName") for f in (folders.json().get("data") or [])]
                print(f"  Mail READ: OK (folders visible: {', '.join(n for n in names if n)[:120]})")
            except ValueError:
                print("  Mail READ: OK")
        else:
            print(f"  Mail READ: HTTP {folders.status_code} — the scope line above must "
                  f"include ZohoMail.messages.READ and ZohoMail.folders.READ "
                  f"({folders.text[:120]})")

    cliq = requests.get(f"{ep['cliq']}/api/v2/channels", headers=bearer_hdr,
                        params={"limit": 100}, timeout=TIMEOUT)
    if cliq.status_code == 200:
        if CLIQ_CHANNEL in cliq.text:
            print(f"  Cliq: OK (channel '{CLIQ_CHANNEL}' found)")
        else:
            print(f"  Cliq: OK, but channel '{CLIQ_CHANNEL}' not found.")
            print(f"        Create it in Cliq (unique name must be '{CLIQ_CHANNEL}').")
    else:
        print(f"  Cliq: HTTP {cliq.status_code} — check ZohoCliq scopes ({cliq.text[:150]})")

    _store("khavion-zoho-client-id", client_id)
    _store("khavion-zoho-client-secret", client_secret)
    _store("khavion-zoho-refresh-token", refresh_token)
    _store("khavion-zoho-region", region)
    print(f"  stored khavion-zoho-client-id     ({_masked(client_id)})")
    print(f"  stored khavion-zoho-client-secret ({_masked(client_secret)})")
    print(f"  stored khavion-zoho-refresh-token ({_masked(refresh_token)})")
    print(f"  stored khavion-zoho-region        ({region})")
    print("  Reminder: Zoho allows max 20 active refresh tokens per client; the oldest")
    print("  dies silently at #21. Do not re-run the grant flow casually.")


def verify() -> None:
    _banner("Verify")
    ok = True
    for service in sorted(ALLOWED_SERVICES):
        value = _read(service)
        if value:
            print(f"  {service:<34} OK  {_masked(value)}")
        else:
            print(f"  {service:<34} MISSING")
            ok = False
    if not ok:
        print("\n  Some entries are missing — run the matching step above.")
        return

    key = _read("khavion-apollo-api-key")
    r = requests.get("https://api.apollo.io/v1/auth/health",
                     headers={"x-api-key": key}, timeout=TIMEOUT)
    print(f"  live: Apollo health            {'OK' if r.status_code == 200 else 'HTTP %s' % r.status_code}")

    region = _read("khavion-zoho-region")
    ep = ZOHO_REGIONS[region]
    r = requests.post(f"{ep['accounts']}/oauth/v2/token", data={
        "grant_type": "refresh_token",
        "client_id": _read("khavion-zoho-client-id"),
        "client_secret": _read("khavion-zoho-client-secret"),
        "refresh_token": _read("khavion-zoho-refresh-token"),
    }, timeout=TIMEOUT)
    good = r.status_code == 200 and "access_token" in (r.json() if r.headers.get(
        "content-type", "").startswith("application/json") else {})
    print(f"  live: Zoho refresh->access     {'OK' if good else 'FAILED (%s)' % r.status_code}")
    print("\n  (SAM.gov not re-checked here to preserve the 10/day quota.)")
    print("\nAll set. Remember: Keychain does not sync — re-run this script on the Mac Mini.")


STEPS = {"apollo": setup_apollo, "sam": setup_sam, "zoho": setup_zoho, "verify": verify}


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg == "all":
        for step in ("apollo", "sam", "zoho", "verify"):
            STEPS[step]()
    elif arg in STEPS:
        STEPS[arg]()
    else:
        raise SystemExit(f"Usage: setup_credentials.py [{'|'.join(STEPS)}|all]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted. Nothing partial was stored beyond the steps that printed 'stored'.")
        sys.exit(130)
