#!/usr/bin/env python3
"""Idempotent cleanup of unused and orphaned Firestore collections in `running-coach`.

Targets:
1. `adk-session/**` sessions (and `events/*`) lacking an `expire_at` field (legacy local/eval runs).
2. `firestore-cyvisser/**` misnamed session root collection (created before `SESSION_URI="firestore://"`).
3. Phantom `users/*` documents (no profile doc and no `private/trainingpeaks` credential, e.g. `alex_runner`
   created by eval runs) and all their subcollections.
4. Legacy `user_states/running_coach/users/*` documents whose ID is not `web_<email>` (e.g. bare email with `runner_id`).

Dry-run by default: prints exact document counts per target without deleting anything. Pass `--apply` to delete.
"""

from __future__ import annotations

import argparse
import os
from typing import Iterable

from google.cloud import firestore

BATCH_LIMIT = 400


def _delete_refs(db: firestore.Client, refs: Iterable[firestore.DocumentReference], apply: bool) -> int:
    ref_list = list(refs)
    if not apply or not ref_list:
        return len(ref_list)
    for start in range(0, len(ref_list), BATCH_LIMIT):
        batch = db.batch()
        for ref in ref_list[start : start + BATCH_LIMIT]:
            batch.delete(ref)
        batch.commit()
    return len(ref_list)


def _collect_session_tree_refs(
    root_col: firestore.CollectionReference,
    *,
    only_missing_ttl: bool,
) -> list[firestore.DocumentReference]:
    """Collects session and event refs under `<root>/<app>/users/<uid>/sessions/<sid>[/events/<eid>]`."""
    refs: list[firestore.DocumentReference] = []
    for app_ref in root_col.list_documents():
        users_col = app_ref.collection("users")
        for user_ref in users_col.list_documents():
            sessions_col = user_ref.collection("sessions")
            for session_ref in sessions_col.list_documents():
                snap = session_ref.get()
                data = snap.to_dict() or {} if snap.exists else {}
                delete_this_session = (not only_missing_ttl) or (not snap.exists) or ("expire_at" not in data)
                if not delete_this_session:
                    continue
                for event_ref in session_ref.collection("events").list_documents():
                    refs.append(event_ref)
                if snap.exists:
                    refs.append(session_ref)
            if not only_missing_ttl and user_ref.get().exists:
                refs.append(user_ref)
        if not only_missing_ttl and app_ref.get().exists:
            refs.append(app_ref)
    return refs


def _collect_phantom_users(
    db: firestore.Client,
) -> dict[str, list[firestore.DocumentReference]]:
    phantom_by_user: dict[str, list[firestore.DocumentReference]] = {}

    for user_ref in db.collection("users").list_documents():
        snap = user_ref.get()
        cred_snap = user_ref.collection("private").document("trainingpeaks").get()
        is_phantom = (not snap.exists) and (not cred_snap.exists)

        if is_phantom:
            bucket: list[firestore.DocumentReference] = []
            for subcol in user_ref.collections():
                for doc_ref in subcol.list_documents():
                    bucket.append(doc_ref)
            if bucket:
                phantom_by_user[user_ref.id] = bucket

    return phantom_by_user


def _collect_legacy_user_states(db: firestore.Client) -> list[firestore.DocumentReference]:
    refs: list[firestore.DocumentReference] = []
    users_col = db.collection("user_states").document("running_coach").collection("users")
    for doc_ref in users_col.list_documents():
        if not doc_ref.id.startswith("web_"):
            refs.append(doc_ref)
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "firestore-cyvisser"))
    parser.add_argument("--database", default=os.environ.get("FIRESTORE_DATABASE", "running-coach"))
    parser.add_argument(
        "--skip-misnamed-root",
        action="store_true",
        help="Skip deleting the misnamed `<project_id>` session root collection",
    )
    parser.add_argument("--apply", action="store_true", help="Execute deletions (default is dry-run)")
    args = parser.parse_args()

    db = firestore.Client(project=args.project, database=args.database)

    adk_legacy_refs = _collect_session_tree_refs(db.collection("adk-session"), only_missing_ttl=True)
    misnamed_refs = (
        []
        if args.skip_misnamed_root
        else _collect_session_tree_refs(db.collection(args.project), only_missing_ttl=False)
    )
    phantom_users = _collect_phantom_users(db)
    legacy_user_state_refs = _collect_legacy_user_states(db)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== Firestore Clutter Cleanup ({mode}) — {args.project}/{args.database} ===")
    print(f"1. adk-session/** (missing expire_at): {len(adk_legacy_refs)} doc(s)")
    if not args.skip_misnamed_root:
        print(f"2. {args.project}/** (misnamed session root): {len(misnamed_refs)} doc(s)")
    print(
        f"3. Phantom users/* subcollections: "
        f"{sum(len(v) for v in phantom_users.values())} doc(s) across {sorted(phantom_users.keys())}"
    )
    print(
        f"4. Legacy user_states/running_coach/users/*: {len(legacy_user_state_refs)} doc(s) "
        f"({[r.id for r in legacy_user_state_refs]})"
    )

    total = 0
    total += _delete_refs(db, adk_legacy_refs, args.apply)
    total += _delete_refs(db, misnamed_refs, args.apply)
    for refs in phantom_users.values():
        total += _delete_refs(db, refs, args.apply)
    total += _delete_refs(db, legacy_user_state_refs, args.apply)

    suffix = "deleted." if args.apply else "matched (re-run with --apply to delete)."
    print(f"\nTotal: {total} document(s) {suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
