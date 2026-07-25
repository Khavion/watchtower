"""Zoho OAuth: refresh-token exchange, region-aware, token cached in memory
only and never written to disk.

Verified 2026-07-24: access tokens live 1 hour; max 10 token requests per
refresh token per 10 minutes, so we refresh only when the cached token is
missing/expiring or after a 401 — never per request. Auth header prefixes
differ by product: CRM and Mail take `Zoho-oauthtoken`, Cliq's documented
samples use `Bearer`.
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

ACCOUNT = "khavion"

REGIONS = {
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


class ZohoAuthError(Exception):
    pass


class ZohoAuth:
    def __init__(self, region: str | None = None, client_id: str | None = None,
                 client_secret: str | None = None, refresh_token: str | None = None,
                 timeout: int = 30):
        self._region = region
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self.timeout = timeout
        # Memory only; never persisted anywhere.
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._api_domain: str | None = None

    def _keychain(self, service: str) -> str:
        import keyring
        value = keyring.get_password(service, ACCOUNT)
        if not value:
            raise ZohoAuthError(
                f"{service} missing from Keychain; run deploy/setup_credentials.py zoho")
        return value

    @property
    def region(self) -> str:
        if not self._region:
            self._region = self._keychain("khavion-zoho-region")
        if self._region not in REGIONS:
            raise ZohoAuthError(f"unknown Zoho region {self._region!r}")
        return self._region

    @property
    def endpoints(self) -> dict:
        return REGIONS[self.region]

    def access_token(self, force_refresh: bool = False) -> str:
        if force_refresh or not self._access_token or time.time() > self._expires_at - 120:
            self._refresh()
        return self._access_token

    def _refresh(self) -> None:
        resp = requests.post(f"{self.endpoints['accounts']}/oauth/v2/token", data={
            "grant_type": "refresh_token",
            "client_id": self._client_id or self._keychain("khavion-zoho-client-id"),
            "client_secret": self._client_secret or self._keychain("khavion-zoho-client-secret"),
            "refresh_token": self._refresh_token or self._keychain("khavion-zoho-refresh-token"),
        }, timeout=self.timeout)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ZohoAuthError(f"token refresh returned non-JSON (HTTP {resp.status_code})") from exc
        if "access_token" not in payload:
            raise ZohoAuthError(f"token refresh failed: {payload.get('error', payload)}")
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 3600))
        self._api_domain = payload.get("api_domain") or self.endpoints["crm_fallback"]
        log.info("zoho: access token refreshed (api_domain %s)", self._api_domain)

    @property
    def api_domain(self) -> str:
        if not self._api_domain:
            self.access_token()
        return self._api_domain

    # Header builders; note the product-specific prefixes.
    def crm_headers(self) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {self.access_token()}"}

    def mail_headers(self) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {self.access_token()}"}

    def cliq_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token()}"}

    def request(self, method: str, url: str, headers_fn, **kwargs) -> requests.Response:
        """One retry on 401 with a forced refresh; otherwise plain."""
        resp = requests.request(method, url, headers=headers_fn(), timeout=self.timeout, **kwargs)
        if resp.status_code == 401:
            log.warning("zoho: 401 from %s, refreshing token once", url.split("?")[0])
            self.access_token(force_refresh=True)
            resp = requests.request(method, url, headers=headers_fn(), timeout=self.timeout, **kwargs)
        return resp
