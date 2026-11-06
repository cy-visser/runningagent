#!/usr/bin/env python3
"""One-time idempotent migration for the existing runner profile in Firestore.

Maps an IAM email (`cyrille@cyvisser.altostrat.com`) to an existing `users/{runner_id}`
document and copies the legacy `tp-auth-cookie` value from Secret Manager (via `gcloud`,
without any Python Secret Manager dependency) into `users/{runner_id}/private/trainingpeaks`,
encrypted with Cloud KMS (`AAD = b"users/{runner_id}"`).

Dry-run by default; pass `--apply` to write to Firestore.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import subprocess
import sys

# Allow importing backend helpers directly when run from running_coach/ or webapp/.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from google.cloud import firestore  # noqa: E402
from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: E402

from app.auth import normalize_email  # noqa: E402
from app.settings import DEFAULT_KMS_KEY_NAME, DEFAULT_KMS_KEY_RING, DEFAULT_KMS_LOCATION  # noqa: E402
from app.trainingpeaks import (  # noqa: E402
    build_credential_document,
    encrypt_tp_cookie_sync,
    validate_tp_cookie,
)


def _read_secret_via_gcloud(project_id: str, secret_name: str) -> str:
    env = {
        **os.environ,
        "CLOUDSDK_METRICS_ENVIRONMENT": (
            f"{os.environ['CLOUDSDK_METRICS_ENVIRONMENT']} datacloud.antigravity"
            if os.environ.get("CLOUDSDK_METRICS_ENVIRONMENT")
            else "datacloud.antigravity"
        ),
    }
    proc = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={secret_name}",
            f"--project={project_id}",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gcloud secrets versions access failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    cookie = proc.stdout.strip()
    if not cookie:
        raise RuntimeError(f"Secret '{secret_name}' returned an empty payload.")
    return cookie


async def _run(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    if not email:
        raise ValueError(f"Invalid email address: {args.email!r}")
    runner_id = args.runner_id.strip().lower()
    kms_key = args.kms_key or (
        f"projects/{args.project}/locations/{DEFAULT_KMS_LOCATION}"
        f"/keyRings/{DEFAULT_KMS_KEY_RING}/cryptoKeys/{DEFAULT_KMS_KEY_NAME}"
    )

    db = firestore.Client(project=args.project, database=args.database)
    user_ref = db.document(f"users/{runner_id}")
    user_snap = user_ref.get()
    if not user_snap.exists:
        raise RuntimeError(f"Firestore document users/{runner_id} does not exist.")
    existing = user_snap.to_dict() or {}

    existing_email = normalize_email(existing.get("email"))
    if existing_email and existing_email != email:
        raise RuntimeError(
            f"users/{runner_id} is already mapped to {existing_email!r} (refusing to overwrite with {email!r})."
        )

    dup_snaps = list(
        db.collection("users").where(filter=FieldFilter("email", "==", email)).limit(2).stream()
    )
    other_ids = [s.id for s in dup_snaps if s.id != runner_id]
    if other_ids:
        raise RuntimeError(
            f"Email {email!r} is already mapped to another runner profile: {', '.join(other_ids)}"
        )

    print(f"[1/4] Verified users/{runner_id} ({existing.get('firstname')} {existing.get('lastname')}).")
    cookie = _read_secret_via_gcloud(args.project, args.secret)
    print(f"[2/4] Read legacy secret '{args.secret}' ({len(cookie)} chars; value redacted).")

    account = await validate_tp_cookie(cookie)
    if account.runner_id != runner_id:
        raise RuntimeError(
            f"TrainingPeaks athlete '{account.tp_name}' maps to '{account.runner_id}', "
            f"expected '{runner_id}'."
        )
    print(
        f"[3/4] Validated TrainingPeaks cookie -> athlete '{account.tp_name}' "
        f"(runner_id={account.runner_id}, athlete_id={account.tp_athlete_id})."
    )

    ciphertext = encrypt_tp_cookie_sync(kms_key, runner_id, account.cookie)
    print(f"[4/4] Encrypted cookie with Cloud KMS key {kms_key} ({len(ciphertext)} bytes ciphertext).")

    if not args.apply:
        print("\nDRY RUN COMPLETE — no Firestore writes performed. Re-run with --apply to commit.")
        return 0

    cred_doc = build_credential_document(account, ciphertext, linked_email=email, source="migration")
    db.document(f"users/{runner_id}/private/trainingpeaks").set(cred_doc)
    user_ref.update({"email": email})
    print(
        f"\nAPPLIED: wrote users/{runner_id}/private/trainingpeaks and set email={email!r} on users/{runner_id}."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-id", required=True, help="Existing Firestore runner document id (e.g. cyrille_visser)")
    parser.add_argument("--email", required=True, help="IAM email to bind (e.g. cyrille@cyvisser.altostrat.com)")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "firestore-cyvisser"))
    parser.add_argument("--database", default=os.environ.get("FIRESTORE_DATABASE", "running-coach"))
    parser.add_argument("--secret", default="tp-auth-cookie", help="Legacy Secret Manager secret name")
    parser.add_argument("--kms-key", default=os.environ.get("TP_COOKIE_KMS_KEY"), help="Full Cloud KMS cryptoKey resource name")
    parser.add_argument("--apply", action="store_true", help="Commit writes to Firestore (default is dry-run)")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
