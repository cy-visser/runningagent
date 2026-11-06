"""Cloud Run Identity-Aware Proxy (IAP) ES256 JWT verification (+ guarded local dev mode).

Access authorization is enforced by Cloud Run IAP IAM (`roles/iap.httpsResourceAccessor`).
This module authenticates the caller by verifying the cryptographic signature, issuer,
audience, and expiry of `X-Goog-IAP-JWT-Assertion`. The unsigned
`X-Goog-Authenticated-User-Email` header is never trusted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any, Callable, Optional

import cachetools
from fastapi import Depends, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
import requests

from .settings import Settings, load_settings

logger = logging.getLogger(__name__)

IAP_ISSUER = "https://cloud.google.com/iap"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
CERTS_TTL_S = 3600.0

_certs_cache: cachetools.TTLCache[str, dict[str, Any]] = cachetools.TTLCache(maxsize=4, ttl=CERTS_TTL_S)


def normalize_email(email: Optional[str]) -> Optional[str]:
    clean = str(email or "").strip().lower()
    if not clean or "@" not in clean or " " in clean:
        return None
    local, _, domain = clean.partition("@")
    return clean if local and "." in domain else None


def derive_initials(firstname: Optional[str], lastname: Optional[str], email: str) -> str:
    fn = (firstname or "").strip()
    ln = (lastname or "").strip()
    if fn and ln:
        return f"{fn[0]}{ln[0]}".upper()
    if fn:
        return fn[:2].upper()
    local = email.split("@", 1)[0]
    parts = [p for p in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if p]
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    return (local[:2] or "RC").upper()


@dataclass(frozen=True)
class AuthenticatedUser:
    email: str
    adk_user_id: str


class _CachedTransport(google_requests.Request):
    """Caches Google IAP public-key JWK responses in-process for 1 hour."""

    def __init__(self) -> None:
        super().__init__(session=requests.Session())

    def __call__(self, url: str, method: str = "GET", body: Any = None, headers: Any = None, timeout: Any = None, **kwargs: Any):  # type: ignore[override]
        if method.upper() == "GET" and url == IAP_CERTS_URL:
            cached = _certs_cache.get(url)
            if cached is not None:
                return cached["response"]
            resp = super().__call__(url, method=method, body=body, headers=headers, timeout=timeout or 10, **kwargs)
            if getattr(resp, "status", 0) == 200:
                _certs_cache[url] = {"response": resp, "at": time.monotonic()}
            return resp
        return super().__call__(url, method=method, body=body, headers=headers, timeout=timeout or 10, **kwargs)


_transport = _CachedTransport()


def verify_iap_assertion_sync(
    assertion: str,
    audience: str,
    transport: Optional[Any] = None,
    certs_url: str = IAP_CERTS_URL,
) -> dict[str, Any]:
    """Verifies an ES256 IAP JWT assertion and returns its decoded claims."""
    if not audience:
        raise ValueError("IAP_AUDIENCE is not configured.")
    claims = id_token.verify_token(
        assertion,
        transport or _transport,
        audience=audience,
        certs_url=certs_url,
    )
    if claims.get("iss") != IAP_ISSUER:
        raise ValueError(f"Unexpected JWT issuer: {claims.get('iss')!r}")
    return claims


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else load_settings()


async def current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """FastAPI dependency returning the IAP-authenticated user (or guarded local dev user)."""
    if settings.auth_mode == "dev":
        if settings.k_service:
            raise HTTPException(status_code=500, detail="Dev auth mode is forbidden on Cloud Run.")
        email = normalize_email(settings.dev_user_email)
        if not email:
            raise HTTPException(status_code=401, detail="DEV_USER_EMAIL is invalid or unset.")
        return AuthenticatedUser(email=email, adk_user_id=f"web_{email}")

    assertion = (request.headers.get("x-goog-iap-jwt-assertion") or "").strip()
    if not assertion:
        raise HTTPException(status_code=401, detail="Missing IAP JWT assertion.")
    if not settings.iap_audience:
        raise HTTPException(status_code=500, detail="IAP_AUDIENCE is not configured.")

    verifier: Callable[[str, str], dict[str, Any]] = getattr(
        request.app.state, "iap_verifier", verify_iap_assertion_sync
    )
    try:
        claims = await asyncio.to_thread(verifier, assertion, settings.iap_audience)
    except Exception as exc:
        logger.warning("IAP JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired IAP session.") from None

    email = normalize_email(claims.get("email"))
    if not email:
        raise HTTPException(status_code=401, detail="IAP assertion contained no valid email claim.")

    return AuthenticatedUser(email=email, adk_user_id=f"web_{email}")
