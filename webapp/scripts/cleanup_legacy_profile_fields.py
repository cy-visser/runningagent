#!/usr/bin/env python3
"""One-time cleanup of legacy free-text runner profile fields in Firestore.

Deletes `recent_race_times` (replaced by structured `personal_records`), string-valued
`shoe_rotation` (replaced by structured shoe slots) and `cross_training_strength` (replaced by
`run_time_of_day` / `strength_time_of_day`) from every `users/*` document. Structured
`shoe_rotation` objects are left untouched, so re-running is safe.

Dry-run by default: prints every affected document with its current values. Pass `--apply` to delete.
"""

from __future__ import annotations

import argparse
import os

from google.cloud import firestore

# Legacy fields deleted whenever present (any value).
_ALWAYS_LEGACY = ("recent_race_times", "cross_training_strength")


def _legacy_fields(doc: dict) -> dict[str, str]:
    legacy = {key: doc[key] for key in _ALWAYS_LEGACY if key in doc}
    if isinstance(doc.get("shoe_rotation"), str):
        legacy["shoe_rotation"] = doc["shoe_rotation"]
    return legacy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "firestore-cyvisser"))
    parser.add_argument("--database", default=os.environ.get("FIRESTORE_DATABASE", "running-coach"))
    parser.add_argument("--apply", action="store_true", help="Delete the legacy fields (default is dry-run)")
    args = parser.parse_args()

    db = firestore.Client(project=args.project, database=args.database)
    affected = 0
    for snap in db.collection("users").stream():
        legacy = _legacy_fields(snap.to_dict() or {})
        if not legacy:
            continue
        affected += 1
        print(f"users/{snap.id}:")
        for key, value in legacy.items():
            print(f"  {key}: {value!r}")
        if args.apply:
            snap.reference.update({key: firestore.DELETE_FIELD for key in legacy})
            print("  -> deleted")

    mode = "APPLIED" if args.apply else "DRY RUN (re-run with --apply to delete)"
    print(f"\n{mode}: {affected} document(s) with legacy fields in {args.project}/{args.database}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
