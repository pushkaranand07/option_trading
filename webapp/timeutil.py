"""IST clock helpers for audit finding L6: one place to ask for "now" and "today" in India time, whatever timezone
the PC runs in. Reuses ``signals.IST`` / ``signals.now_ist`` (the existing helper); this module only adds the date
form and gives code outside signals one import. Don't use it inside the fingerprinted functions
(docs/audit/fingerprint_map.md)."""

from __future__ import annotations

from datetime import date

from webapp.signals import IST, now_ist

__all__ = ["IST", "now_ist", "today_ist"]


def today_ist() -> date:
    """Today's date in India, not the PC's local date."""
    return now_ist().date()
