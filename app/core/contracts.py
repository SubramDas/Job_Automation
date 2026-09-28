"""Shared Phase 01 contracts.

These constants are intentionally small and deterministic. Later phases can add persistence
and adapters, but state names and error codes should remain explicit.
"""

from __future__ import annotations

ERROR_CODES: tuple[str, ...] = (
    "missing_fact",
    "stale_fact",
    "conflicting_fact",
    "unsupported_source",
    "authorization_required",
    "authorization_failed",
    "rate_limited",
    "duplicate_risk",
    "schema_invalid",
    "config_invalid",
    "private_data_blocked",
)

CAPABILITY_FLAGS: tuple[str, ...] = (
    "discovery",
    "result_link_retrieval",
    "description_retrieval",
    "destination_resolution",
    "manual_handoff",
    "fixture",
    "api_candidate",
    "import_only",
)
