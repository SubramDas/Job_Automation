"""Shared Phase 01 contracts.

These constants are intentionally small and deterministic. Later phases can add persistence
and adapters, but state names and error codes should remain explicit.
"""

from __future__ import annotations

APPLICATION_STATES: tuple[str, ...] = (
    "discovered",
    "extracted",
    "evaluated",
    "shortlisted",
    "tailoring",
    "validated",
    "preparing",
    "ready",
    "submitting",
    "submitted",
    "rejected_by_preferences",
    "needs_user_input",
    "needs_review",
    "manual_handoff",
    "expired",
    "retryable_failure",
    "permanent_failure",
    "submission_unknown",
    "cancelled",
)

NORMAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "discovered": ("extracted", "rejected_by_preferences", "manual_handoff", "cancelled"),
    "extracted": ("evaluated", "needs_review", "retryable_failure", "cancelled"),
    "evaluated": ("shortlisted", "rejected_by_preferences", "needs_review", "cancelled"),
    "shortlisted": ("tailoring", "needs_review", "cancelled"),
    "tailoring": ("validated", "needs_user_input", "retryable_failure", "cancelled"),
    "validated": ("preparing", "needs_review", "cancelled"),
    "preparing": ("ready", "needs_user_input", "manual_handoff", "retryable_failure", "cancelled"),
    "ready": ("submitting", "needs_review", "manual_handoff", "cancelled"),
    "submitting": ("submitted", "submission_unknown", "retryable_failure", "permanent_failure"),
    "submission_unknown": ("submitted", "manual_handoff", "permanent_failure"),
    "needs_user_input": ("tailoring", "preparing", "cancelled"),
    "needs_review": ("shortlisted", "ready", "manual_handoff", "cancelled"),
    "retryable_failure": ("extracted", "tailoring", "preparing", "ready", "permanent_failure"),
}

ERROR_CODES: tuple[str, ...] = (
    "missing_fact",
    "stale_fact",
    "conflicting_fact",
    "unsupported_source",
    "unsupported_form",
    "authorization_required",
    "authorization_failed",
    "rate_limited",
    "duplicate_risk",
    "submission_uncertain",
    "schema_invalid",
    "config_invalid",
    "private_data_blocked",
    "external_action_disabled",
)

CAPABILITY_FLAGS: tuple[str, ...] = (
    "discovery",
    "result_link_retrieval",
    "description_retrieval",
    "destination_resolution",
    "draft_fill",
    "upload",
    "submission",
    "reconciliation",
    "manual_handoff",
    "fixture",
    "api_candidate",
    "import_only",
)
