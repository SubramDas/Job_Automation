"""Persist user review actions for Agent B discovery results."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.matching.calibration import LabeledMatchCase, evaluate_labeled_matches, suggest_thresholds
from app.storage.space import SpacePaths, SpaceStore, new_id, stable_json, utc_now

VALID_ACTIONS = {
    "accept_shortlist",
    "reject_job",
    "mark_duplicate",
    "request_manual_import",
    "label",
}
VALID_LABELS = {"yes", "maybe", "no"}


@dataclass(frozen=True)
class ReviewActionResult:
    action_id: str
    action: str
    label: str | None
    job_id: str | None
    run_id: str | None


def record_agent_b_review_action(
    store: SpaceStore,
    *,
    action: str,
    run_id: str | None = None,
    job_id: str | None = None,
    label: str | None = None,
    reason: str | None = None,
    source_feedback: dict[str, Any] | None = None,
    actor: str = "user",
) -> ReviewActionResult:
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported review action: {action}")
    if action == "label" and label not in VALID_LABELS:
        raise ValueError("label actions require one of: yes, maybe, no")
    if action != "label" and label is not None:
        raise ValueError("labels are only valid with action=label")
    if not run_id and not job_id:
        raise ValueError("review action requires run_id or job_id")

    action_id = new_id("agent_b_review")
    now = utc_now()
    details = {
        "run_id": run_id,
        "job_id": job_id,
        "action": action,
        "label": label,
        "reason_present": bool(reason),
        "source_feedback_keys": sorted((source_feedback or {}).keys()),
    }
    with store.connect() as db:
        db.execute(
            """
            INSERT INTO agent_b_review_actions
              (id, run_id, job_id, action, label, reason, source_feedback_json, actor, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                run_id,
                job_id,
                action,
                label,
                reason,
                stable_json(source_feedback or {}),
                actor,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO audit_events
              (id, actor, event_type, subject_type, subject_id, details_json, created_at)
            VALUES (?, ?, 'agent_b_review_action', 'job', ?, ?, ?)
            """,
            (
                new_id("audit"),
                actor,
                job_id or run_id or action_id,
                stable_json(details),
                now,
            ),
        )
    return ReviewActionResult(
        action_id=action_id,
        action=action,
        label=label,
        job_id=job_id,
        run_id=run_id,
    )


def evaluate_agent_b_review_labels(store: SpaceStore) -> dict[str, Any]:
    """Summarize persisted yes/maybe/no labels against latest Agent B decisions."""
    cases: list[LabeledMatchCase] = []
    with store.connect() as db:
        rows = db.execute(
            """
            SELECT action.id AS action_id, action.label, action.job_id,
                   match.decision, match.score
            FROM agent_b_review_actions AS action
            JOIN match_results AS match ON match.job_id = action.job_id
            WHERE action.action = 'label'
              AND action.label IS NOT NULL
              AND match.created_at = (
                SELECT MAX(created_at) FROM match_results WHERE job_id = action.job_id
              )
            ORDER BY action.created_at
            """
        ).fetchall()
    for row in rows:
        cases.append(
            LabeledMatchCase(
                case_id=row["action_id"],
                user_label=row["label"],
                system_decision=row["decision"],
                score=row["score"],
            )
        )
    return {
        "case_count": len(cases),
        "quality": evaluate_labeled_matches(cases),
        "suggested_thresholds": suggest_thresholds(cases),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Record a review action for an Agent B result.")
    parser.add_argument("--project-root", default=".", help="Project root containing private Space data.")
    parser.add_argument("--run-id")
    parser.add_argument("--job-id")
    parser.add_argument("--action", choices=sorted(VALID_ACTIONS))
    parser.add_argument("--label", choices=sorted(VALID_LABELS))
    parser.add_argument("--reason")
    parser.add_argument("--source-feedback-json", default="{}")
    parser.add_argument("--evaluate-labels", action="store_true")
    args = parser.parse_args()

    store = SpaceStore(SpacePaths.from_project_root(Path(args.project_root).resolve()))
    store.migrate()
    if args.evaluate_labels:
        print(stable_json(evaluate_agent_b_review_labels(store)))
        return 0
    if not args.action:
        parser.error("--action is required unless --evaluate-labels is used")
    result = record_agent_b_review_action(
        store,
        action=args.action,
        run_id=args.run_id,
        job_id=args.job_id,
        label=args.label,
        reason=args.reason,
        source_feedback=json.loads(args.source_feedback_json),
    )
    print(stable_json(result.__dict__))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
