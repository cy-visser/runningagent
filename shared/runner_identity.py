"""Canonical runner identity helpers (email normalisation and Firestore document IDs)."""

from typing import Optional


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Returns a canonical lowercase email address, or None when absent/invalid."""
    clean = str(email or "").strip().lower()
    if not clean or "@" not in clean or " " in clean:
        return None
    local, _, domain = clean.partition("@")
    return clean if local and "." in domain else None


def get_user_id(firstname: Optional[str], lastname: Optional[str] = "") -> str:
    """Returns the canonical lowercase user_id for Firestore document keys."""
    fn = str(firstname or "").strip().lower()
    ln = str(lastname or "").strip().lower()
    return f"{fn}_{ln}"


def profile_user_id(profile: Optional[dict]) -> Optional[str]:
    """Returns the Firestore user_id for a profile, or None when it has no name."""
    profile = profile or {}
    user_id = get_user_id(profile.get("firstname"), profile.get("lastname"))
    return None if user_id == "_" else user_id
