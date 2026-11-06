"""Behavioural test for Cloud Run IAP ES256 JWT verification, dev-mode startup guards, and unsigned header rejection."""

from __future__ import annotations

import json
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
import pytest

from app.auth import IAP_ISSUER, verify_iap_assertion_sync
from app.settings import Settings, validate_startup_settings
from conftest import AUDIENCE, EMAIL, build_test_app


def _make_es256_signer_and_certs():
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signer = crypt.ES256Signer.from_string(priv_pem, key_id="iap-key-1")
    certs_body = json.dumps({"iap-key-1": pub_pem.decode("utf-8")}).encode("utf-8")

    class FakeResponse:
        status = 200
        data = certs_body
        headers = {}

    def fake_transport(url, method="GET", **kwargs):
        return FakeResponse()

    return signer, fake_transport


def _encode_jwt(signer, *, iss=IAP_ISSUER, aud=AUDIENCE, email=EMAIL, exp_offset=300):
    now = int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "email": email,
        "sub": "accounts.google.com:12345",
        "iat": now - 5,
        "exp": now + exp_offset,
    }
    token = jwt.encode(signer, payload)
    return token.decode("utf-8") if isinstance(token, bytes) else token


def test_iap_jwt_verification_dev_mode_guard_and_unsigned_header_rejection():
    signer, transport = _make_es256_signer_and_certs()

    # Valid ES256 IAP JWT
    valid_token = _encode_jwt(signer)
    claims = verify_iap_assertion_sync(valid_token, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")
    assert claims["email"] == EMAIL

    # Wrong audience
    wrong_aud = _encode_jwt(signer, aud="/projects/999/locations/europe-west4/services/other")
    with pytest.raises(ValueError):
        verify_iap_assertion_sync(wrong_aud, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")

    # Wrong issuer
    wrong_iss = _encode_jwt(signer, iss="https://accounts.google.com")
    with pytest.raises(ValueError, match="issuer"):
        verify_iap_assertion_sync(wrong_iss, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")

    # Expired JWT
    expired = _encode_jwt(signer, exp_offset=-600)
    with pytest.raises(ValueError):
        verify_iap_assertion_sync(expired, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")

    # AUTH_MODE=dev forbidden when K_SERVICE is set on Cloud Run
    settings = Settings(
        auth_mode="dev",
        iap_audience=None,
        dev_user_email=EMAIL,
        project_id="firestore-cyvisser",
        firestore_database="running-coach",
        tp_cookie_kms_key="key",
        agent_runtime_resource="projects/1/locations/europe-west4/reasoningEngines/2",
        agent_base_url=None,
        agent_app_name="running_coach",
        static_dir="/tmp/none",
        k_service="running-coach-web",
    )
    with pytest.raises(RuntimeError, match="AUTH_MODE=dev"):
        validate_startup_settings(settings)

    # Unauthenticated request and unsigned X-Goog-Authenticated-User-Email header rejected with 401
    app, _, _ = build_test_app()
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        r = client.get("/api/me", headers={"X-Goog-Authenticated-User-Email": f"accounts.google.com:{EMAIL}"})
        assert r.status_code == 401
