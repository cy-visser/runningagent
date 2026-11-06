"""Tests for Cloud Run IAP ES256 JWT verification and dev-mode startup guards."""

from __future__ import annotations

import json
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from google.auth import crypt, jwt
import pytest

from app.auth import IAP_ISSUER, verify_iap_assertion_sync
from app.settings import Settings, validate_startup_settings

AUDIENCE = "/projects/840839653849/locations/europe-west4/services/running-coach-web"


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


def _encode_jwt(signer, *, iss=IAP_ISSUER, aud=AUDIENCE, email="cyrille@cyvisser.altostrat.com", exp_offset=300):
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


def test_verify_valid_es256_iap_jwt():
    signer, transport = _make_es256_signer_and_certs()
    token = _encode_jwt(signer)
    claims = verify_iap_assertion_sync(token, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")
    assert claims["email"] == "cyrille@cyvisser.altostrat.com"


def test_rejects_wrong_audience():
    signer, transport = _make_es256_signer_and_certs()
    token = _encode_jwt(signer, aud="/projects/999/locations/europe-west4/services/other")
    with pytest.raises(ValueError):
        verify_iap_assertion_sync(token, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")


def test_rejects_wrong_issuer():
    signer, transport = _make_es256_signer_and_certs()
    token = _encode_jwt(signer, iss="https://accounts.google.com")
    with pytest.raises(ValueError, match="issuer"):
        verify_iap_assertion_sync(token, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")


def test_rejects_expired_jwt():
    signer, transport = _make_es256_signer_and_certs()
    token = _encode_jwt(signer, exp_offset=-600)
    with pytest.raises(ValueError):
        verify_iap_assertion_sync(token, AUDIENCE, transport=transport, certs_url="https://certs.local/iap")


def test_dev_auth_mode_forbidden_when_k_service_set():
    settings = Settings(
        auth_mode="dev",
        iap_audience=None,
        dev_user_email="cyrille@cyvisser.altostrat.com",
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
