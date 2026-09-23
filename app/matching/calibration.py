"""Phase 05 calibration helpers for labeled Agent B results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.model_runtime import ModelRouter


@dataclass(frozen=True)
class LabeledMatchCase:
    case_id: str
    user_label: str
    system_decision: str
    score: float | None
    held_out: bool = False
    ambiguous: bool = False


def evaluate_labeled_matches(cases: list[LabeledMatchCase]) -> dict[str, Any]:
    """Summarize shortlist quality for yes/maybe/no calibration sets."""
    if not cases:
        return {
            "case_count": 0,
            "held_out_count": 0,
            "shortlist_acceptance": None,
            "known_hard_filter_escape_count": 0,
            "confusion": {},
        }

    confusion: dict[str, dict[str, int]] = {}
    shortlisted = [case for case in cases if case.system_decision == "shortlisted"]
    accepted_shortlisted = [case for case in shortlisted if case.user_label in {"yes", "maybe"}]
    hard_filter_escapes = [
        case for case in cases if case.user_label == "no" and case.system_decision == "shortlisted"
    ]
    for case in cases:
        confusion.setdefault(case.user_label, {})
        confusion[case.user_label][case.system_decision] = (
            confusion[case.user_label].get(case.system_decision, 0) + 1
        )
    return {
        "case_count": len(cases),
        "held_out_count": sum(1 for case in cases if case.held_out),
        "shortlist_acceptance": (
            round(len(accepted_shortlisted) / len(shortlisted), 2) if shortlisted else None
        ),
        "known_hard_filter_escape_count": len(hard_filter_escapes),
        "confusion": confusion,
    }


def suggest_thresholds(cases: list[LabeledMatchCase]) -> dict[str, Any]:
    """Suggest conservative thresholds from labeled non-held-out cases."""
    training = [case for case in cases if not case.held_out and case.score is not None]
    positive_scores = [case.score for case in training if case.user_label == "yes"]
    maybe_scores = [case.score for case in training if case.user_label == "maybe"]
    negative_scores = [case.score for case in training if case.user_label == "no"]
    if not training or not positive_scores:
        return {
            "shortlist_threshold": 80,
            "review_threshold": 65,
            "basis": "defaults_used_until_labeled_training_cases_exist",
        }
    min_positive = min(positive_scores)
    max_negative = max(negative_scores) if negative_scores else 0
    review_floor = min(maybe_scores) if maybe_scores else 65
    return {
        "shortlist_threshold": max(80, round((min_positive + max_negative) / 2, 2)),
        "review_threshold": min(65, review_floor),
        "basis": "synthetic_or_user_labeled_training_cases",
    }


def evaluate_agent_b_model_routes(
    project_root: Path,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Record default/escalated Agent B synthetic model routes and estimated cost."""
    router = ModelRouter(project_root)
    routes = []
    for case in cases:
        routes.append(
            router.route(
                agent_id="agent_b_discovery",
                stage=case.get("stage", "job_extraction"),
                payload={"description": case["description"], "ambiguous": bool(case.get("ambiguous"))},
                output_schema={"type": "object"},
                escalation_attempt=1 if case.get("ambiguous") else 0,
            )
        )
    return {
        "case_count": len(cases),
        "routes": [
            {
                "selected_model": route.selected_model,
                "route_status": route.route_status,
                "estimated_tokens": route.estimated_tokens,
                "estimated_cost": route.estimated_cost,
            }
            for route in routes
        ],
        "total_estimated_cost": round(sum(route.estimated_cost for route in routes), 8),
    }
