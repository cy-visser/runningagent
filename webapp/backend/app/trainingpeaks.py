"""TrainingPeaks `Production_tpAuth` validation, runner_id derivation, and Cloud KMS encryption."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Optional

from google.cloud import kms
import httpx

TP_API_BASE = "https://tpapi.trainingpeaks.com"
COOKIE_NAME = "Production_tpAuth"


class TrainingPeaksValidationError(ValueError):
    """Raised when a supplied cookie is empty or rejected by TrainingPeaks."""


class ConnectConflictError(RuntimeError):
    """Raised on 409 runner_id / email conflicts when connecting TrainingPeaks."""


@dataclass(frozen=True)
class ValidatedTpAccount:
    cookie: str
    firstname: str
    lastname: str
    runner_id: str
    tp_name: str
    tp_user_id: Optional[int]
    tp_athlete_id: Optional[int]


def clean_tp_cookie_input(raw: str) -> str:
    """Normalizes a pasted cookie value (strips quotes or leading `Production_tpAuth=`)."""
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise TrainingPeaksValidationError("Please paste your Production_tpAuth cookie value.")
    # Support users pasting `Production_tpAuth=xyz; other=1` from DevTools headers.
    match = re.search(r"(?:^|;\s*)Production_tpAuth=([^;\s]+)", text)
    if match:
        text = match.group(1).strip()
    if not text or any(ch.isspace() for ch in text):
        raise TrainingPeaksValidationError(
            "Cookie value contains whitespace or is invalid. Copy only the Production_tpAuth value."
        )
    return text


def derive_runner_identity(first_name: Optional[str], last_name: Optional[str], full_name: Optional[str]) -> tuple[str, str, str]:
    """Derives `(firstname, lastname, runner_id)` using the exact canonical rule as the agent."""
    fn = str(first_name or "").strip()
    ln = str(last_name or "").strip()
    if not fn and full_name:
        parts = str(full_name).strip().split(maxsplit=1)
        fn = parts[0] if parts else ""
        ln = parts[1] if len(parts) > 1 else ""
    runner_id = f"{fn.lower()}_{ln.lower()}"
    if not fn or runner_id == "_":
        raise TrainingPeaksValidationError("TrainingPeaks account has no athlete name.")
    return fn, ln, runner_id


async def validate_tp_cookie(
    raw_cookie: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> ValidatedTpAccount:
    """Exchanges `Production_tpAuth` for an OAuth token and reads the athlete profile."""
    cookie = clean_tp_cookie_input(raw_cookie)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    try:
        token_resp = await client.get(
            f"{TP_API_BASE}/users/v3/token",
            headers={
                "Cookie": f"{COOKIE_NAME}={cookie}",
                "Accept": "application/json",
                "User-Agent": "RunningCoachWeb/1.0",
            },
        )
        if token_resp.status_code in (401, 403):
            raise TrainingPeaksValidationError(
                "TrainingPeaks rejected this cookie (expired or invalid Production_tpAuth)."
            )
        if token_resp.status_code != 200:
            raise TrainingPeaksValidationError(
                f"TrainingPeaks token check returned HTTP {token_resp.status_code}."
            )
        token_json = token_resp.json()
        if not isinstance(token_json, dict) or token_json.get("success") is False:
            raise TrainingPeaksValidationError("TrainingPeaks rejected the authentication cookie.")
        token_obj = token_json.get("token") if isinstance(token_json.get("token"), dict) else token_json
        access_token = (token_obj or {}).get("access_token")
        if not access_token:
            raise TrainingPeaksValidationError("TrainingPeaks did not return an access token for this cookie.")

        user_resp = await client.get(
            f"{TP_API_BASE}/users/v3/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "RunningCoachWeb/1.0",
            },
        )
        if user_resp.status_code != 200:
            raise TrainingPeaksValidationError(
                f"TrainingPeaks user lookup returned HTTP {user_resp.status_code}."
            )
        user_json = user_resp.json()
        user_obj = user_json.get("user") if isinstance(user_json, dict) and isinstance(user_json.get("user"), dict) else user_json
        if not isinstance(user_obj, dict):
            raise TrainingPeaksValidationError("Unexpected TrainingPeaks user response.")

        fn, ln, runner_id = derive_runner_identity(
            user_obj.get("firstName"),
            user_obj.get("lastName"),
            user_obj.get("fullName") or user_obj.get("name"),
        )
        tp_name = f"{fn} {ln}".strip()
        raw_uid = user_obj.get("userId")
        raw_aid = user_obj.get("personId") or user_obj.get("athleteId")
        return ValidatedTpAccount(
            cookie=cookie,
            firstname=fn,
            lastname=ln,
            runner_id=runner_id,
            tp_name=tp_name,
            tp_user_id=int(raw_uid) if isinstance(raw_uid, (int, float)) else None,
            tp_athlete_id=int(raw_aid) if isinstance(raw_aid, (int, float)) else None,
        )
    except httpx.RequestError as exc:
        raise TrainingPeaksValidationError(f"Could not reach TrainingPeaks: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()


def credential_aad(runner_id: str) -> bytes:
    return f"users/{runner_id}".encode("utf-8")


def encrypt_tp_cookie_sync(
    kms_key_name: str,
    runner_id: str,
    cookie: str,
    kms_client: Optional[kms.KeyManagementServiceClient] = None,
) -> bytes:
    """Encrypts a runner's TrainingPeaks cookie with Cloud KMS and runner-bound AAD."""
    if not kms_key_name:
        raise RuntimeError("TP_COOKIE_KMS_KEY is not configured.")
    client = kms_client or kms.KeyManagementServiceClient()
    response = client.encrypt(
        request={
            "name": kms_key_name,
            "plaintext": cookie.encode("utf-8"),
            "additional_authenticated_data": credential_aad(runner_id),
        }
    )
    return bytes(response.ciphertext)


def build_credential_document(
    account: ValidatedTpAccount,
    ciphertext: bytes,
    linked_email: str,
    source: str = "web",
) -> dict[str, Any]:
    return {
        "cookie_ciphertext": ciphertext,
        "tp_name": account.tp_name,
        "tp_user_id": account.tp_user_id,
        "tp_athlete_id": account.tp_athlete_id,
        "linked_email": linked_email,
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
