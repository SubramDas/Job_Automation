"""Phase 07 answer-memory and question workflow.

This module keeps answer reuse deterministic. Similar wording may help create a
question, but only exact semantic keys with compatible scope, type/unit, freshness,
and reuse permission can resolve automatically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage.space import SpaceError, SpaceStore, new_id, stable_json, utc_now

TERMINAL_APPLICATION_STATES = {"submitted", "cancelled", "permanent_failure"}
QUESTION_TERMINAL_STATUSES = {"answered", "manual_handoff", "skipped"}

SPECIAL_REVIEW_PREFIXES = (
    "optional_demographic.",
    "consent.",
    "attestation.",
    "signature.",
    "employer_disclosure.",
    "conflict_of_interest.",
)

FIELD_CONTEXT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "availability.notice_period_days": ("country", "employment_type"),
    "availability.earliest_start_date": ("country", "employment_type"),
    "compensation.expected_annual_fixed": ("country", "employment_type", "currency", "unit"),
    "compensation.expected_annual_total": ("country", "employment_type", "currency", "unit"),
    "compensation.hourly_rate": ("country", "employment_type", "currency", "unit"),
    "work_authorization.country_code": ("country",),
    "work_authorization.needs_sponsorship": ("country",),
    "experience.years_total": ("experience_definition",),
    "experience.years_professional": ("experience_definition",),
    "experience.years_skill": ("skill", "experience_definition"),
}

DEFAULT_FRESHNESS_DAYS: dict[str, int] = {
    "availability.notice_period_days": 90,
    "availability.earliest_start_date": 30,
    "compensation.expected_annual_fixed": 90,
    "compensation.expected_annual_total": 90,
    "compensation.hourly_rate": 90,
}


@dataclass(frozen=True)
class AnswerResolution:
    status: str
    answer_id: str | None
    reason: str | None
    question_id: str | None
    candidates: tuple[str, ...]
    required_context: dict[str, Any]


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_load(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


def canonical_context(context: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values and sort nested JSON for stable equality checks."""
    normalized: dict[str, Any] = {}
    for key, value in context.items():
        if value is None or value == "":
            continue
        normalized[key] = value
    return json.loads(stable_json(normalized))


def required_context_for(semantic_key: str, context: dict[str, Any]) -> dict[str, Any]:
    keys = FIELD_CONTEXT_REQUIREMENTS.get(semantic_key, ())
    return {key: context[key] for key in keys if key in context and context[key] not in (None, "")}


def missing_required_context(semantic_key: str, context: dict[str, Any]) -> list[str]:
    required = FIELD_CONTEXT_REQUIREMENTS.get(semantic_key, ())
    return [key for key in required if context.get(key) in (None, "")]


def is_special_review_key(semantic_key: str) -> bool:
    return semantic_key.startswith(SPECIAL_REVIEW_PREFIXES)


class AnswerMemoryService:
    """Resolve reusable answers and manage resumable user questions."""

    def __init__(self, store: SpaceStore) -> None:
        self.store = store

    def resolve_answer(
        self,
        *,
        semantic_key: str,
        context: dict[str, Any],
        expected_type: str | None = None,
        unit: str | None = None,
        application_id: str | None = None,
        original_question: str | None = None,
        create_question: bool = False,
        reason: str | None = None,
        suggested_reuse_scope: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> AnswerResolution:
        normalized_context = canonical_context(context)
        required_context = required_context_for(semantic_key, normalized_context)
        missing = missing_required_context(semantic_key, normalized_context)
        if missing:
            return self._unresolved(
                status="missing_context",
                semantic_key=semantic_key,
                context=normalized_context,
                application_id=application_id,
                original_question=original_question,
                reason=f"missing required context: {', '.join(missing)}",
                suggested_reuse_scope=suggested_reuse_scope,
                create_question=create_question,
                checkpoint=checkpoint,
                candidates=(),
                required_context=required_context,
            )
        if is_special_review_key(semantic_key):
            return self._unresolved(
                status="needs_explicit_review",
                semantic_key=semantic_key,
                context=normalized_context,
                application_id=application_id,
                original_question=original_question,
                reason="sensitive declaration requires explicit applicable approval",
                suggested_reuse_scope=suggested_reuse_scope,
                create_question=create_question,
                checkpoint=checkpoint,
                candidates=(),
                required_context=required_context,
            )

        with self.store.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM reusable_answers
                WHERE semantic_key = ?
                  AND confirmation_state = 'confirmed'
                ORDER BY version DESC, created_at DESC
                """,
                (semantic_key,),
            ).fetchall()

        now = _parse_utc(utc_now())
        compatible: list[dict[str, Any]] = []
        stale_candidates: list[str] = []
        incompatible_candidates: list[str] = []
        for row in rows:
            row_dict = dict(row)
            answer_scope = canonical_context(_json_load(row_dict["scope_json"], {}))
            compatibility = self._compatibility_reason(
                answer=row_dict,
                answer_scope=answer_scope,
                requested_context=normalized_context,
                required_context=required_context,
                expected_type=expected_type,
                unit=unit,
            )
            if compatibility is not None:
                incompatible_candidates.append(row_dict["id"])
                continue
            if self._is_stale(row_dict, semantic_key, now):
                stale_candidates.append(row_dict["id"])
                continue
            compatible.append(row_dict)

        if len(compatible) == 1:
            return AnswerResolution(
                status="resolved",
                answer_id=str(compatible[0]["id"]),
                reason=None,
                question_id=None,
                candidates=(str(compatible[0]["id"]),),
                required_context=required_context,
            )
        if len(compatible) > 1:
            distinct = {
                (
                    row["typed_value_json"],
                    row["unit"],
                    stable_json(canonical_context(_json_load(row["scope_json"], {}))),
                )
                for row in compatible
            }
            if len(distinct) == 1:
                chosen = compatible[0]
                return AnswerResolution(
                    status="resolved",
                    answer_id=str(chosen["id"]),
                    reason=None,
                    question_id=None,
                    candidates=tuple(str(row["id"]) for row in compatible),
                    required_context=required_context,
                )
            return self._unresolved(
                status="conflict",
                semantic_key=semantic_key,
                context=normalized_context,
                application_id=application_id,
                original_question=original_question,
                reason="multiple compatible confirmed answers conflict",
                suggested_reuse_scope=suggested_reuse_scope,
                create_question=create_question,
                checkpoint=checkpoint,
                candidates=tuple(str(row["id"]) for row in compatible),
                required_context=required_context,
            )

        if stale_candidates:
            status = "stale"
            unresolved_reason = "matching answer requires reconfirmation"
            candidates = tuple(stale_candidates)
        elif incompatible_candidates:
            status = "incompatible"
            unresolved_reason = "answers exist but scope, type, unit, or permission is incompatible"
            candidates = tuple(incompatible_candidates)
        else:
            status = "missing"
            unresolved_reason = reason or "no compatible confirmed answer"
            candidates = ()
        return self._unresolved(
            status=status,
            semantic_key=semantic_key,
            context=normalized_context,
            application_id=application_id,
            original_question=original_question,
            reason=unresolved_reason,
            suggested_reuse_scope=suggested_reuse_scope,
            create_question=create_question,
            checkpoint=checkpoint,
            candidates=candidates,
            required_context=required_context,
        )

    def create_or_get_question(
        self,
        *,
        application_id: str | None,
        field_context: dict[str, Any],
        reason: str,
        suggested_reuse_scope: dict[str, Any] | None,
    ) -> str:
        normalized_context = canonical_context(field_context)
        encoded_context = stable_json(normalized_context)
        encoded_scope = stable_json(canonical_context(suggested_reuse_scope or {}))
        with self.store.connect() as db:
            row = db.execute(
                """
                SELECT id FROM pending_questions
                WHERE status = 'open'
                  AND ((application_id IS NULL AND ? IS NULL) OR application_id = ?)
                  AND field_context_json = ?
                  AND COALESCE(suggested_reuse_scope_json, '{}') = ?
                ORDER BY created_at
                LIMIT 1
                """,
                (application_id, application_id, encoded_context, encoded_scope),
            ).fetchone()
            if row is not None:
                return str(row["id"])
            question_id = new_id("question")
            now = utc_now()
            db.execute(
                """
                INSERT INTO pending_questions
                  (id, application_id, field_context_json, reason, suggested_reuse_scope_json,
                   status, answer_ref, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'open', NULL, ?, ?)
                """,
                (
                    question_id,
                    application_id,
                    encoded_context,
                    reason,
                    encoded_scope if suggested_reuse_scope is not None else None,
                    now,
                    now,
                ),
            )
        return question_id

    def batch_questions(self, questions: list[dict[str, Any]]) -> list[str]:
        return [
            self.create_or_get_question(
                application_id=question.get("application_id"),
                field_context=question["field_context"],
                reason=question["reason"],
                suggested_reuse_scope=question.get("suggested_reuse_scope"),
            )
            for question in questions
        ]

    def answer_question(
        self,
        *,
        question_id: str,
        typed_value: Any,
        unit: str | None,
        sensitivity: str,
        reuse_permission: str,
        scope: dict[str, Any],
        provenance: dict[str, Any],
        expires_at: str | None,
        actor: str,
    ) -> str:
        if actor != "user":
            raise SpaceError("only the authenticated user workflow can answer pending questions")
        now = utc_now()
        with self.store.connect() as db:
            question = db.execute(
                "SELECT * FROM pending_questions WHERE id = ?",
                (question_id,),
            ).fetchone()
            if question is None:
                raise SpaceError(f"unknown question: {question_id}")
            if question["status"] in QUESTION_TERMINAL_STATUSES:
                raise SpaceError("question is already resolved")
            field_context = _json_load(question["field_context_json"], {})
            semantic_key = field_context.get("semantic_key")
            original_question = field_context.get("original_question") or field_context.get("label")
            if not semantic_key:
                raise SpaceError("question field context does not include semantic_key")
            answer_id = new_id("answer")
            db.execute(
                """
                INSERT INTO reusable_answers
                  (id, semantic_key, original_question, typed_value_json, unit, scope_json,
                   confirmation_state, expires_at, sensitivity, reuse_permission,
                   provenance_json, version, supersedes_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, 1, NULL, ?, ?)
                """,
                (
                    answer_id,
                    semantic_key,
                    original_question or question["reason"],
                    stable_json(typed_value),
                    unit,
                    stable_json(canonical_context(scope)),
                    expires_at,
                    sensitivity,
                    reuse_permission,
                    stable_json(provenance),
                    now,
                    now,
                ),
            )
            db.execute(
                """
                UPDATE pending_questions
                SET status = 'answered', answer_ref = ?, updated_at = ?
                WHERE id = ?
                """,
                (answer_id, now, question_id),
            )
            application_id = question["application_id"]
            if application_id:
                self._resume_application(db, application_id, answer_id, now)
        return answer_id

    def revise_answer(
        self,
        answer_id: str,
        *,
        typed_value: Any,
        unit: str | None,
        scope: dict[str, Any],
        provenance: dict[str, Any],
        expires_at: str | None,
        actor: str,
        reason: str,
    ) -> str:
        if actor != "user":
            raise SpaceError("only the authenticated user workflow can revise reusable answers")
        now = utc_now()
        with self.store.connect() as db:
            old = db.execute("SELECT * FROM reusable_answers WHERE id = ?", (answer_id,)).fetchone()
            if old is None:
                raise SpaceError(f"unknown answer: {answer_id}")
            db.execute(
                """
                UPDATE reusable_answers
                SET confirmation_state = 'superseded', updated_at = ?
                WHERE id = ?
                """,
                (now, answer_id),
            )
            replacement_id = new_id("answer")
            db.execute(
                """
                INSERT INTO reusable_answers
                  (id, semantic_key, original_question, typed_value_json, unit, scope_json,
                   confirmation_state, expires_at, sensitivity, reuse_permission,
                   provenance_json, version, supersedes_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    replacement_id,
                    old["semantic_key"],
                    old["original_question"],
                    stable_json(typed_value),
                    unit,
                    stable_json(canonical_context(scope)),
                    expires_at,
                    old["sensitivity"],
                    old["reuse_permission"],
                    stable_json(provenance),
                    int(old["version"]) + 1,
                    answer_id,
                    now,
                    now,
                ),
            )
            self._invalidate_answer_users(db, answer_id, replacement_id, reason)
        return replacement_id

    def set_question_status(
        self,
        question_id: str,
        *,
        status: str,
        actor: str,
        reason: str,
    ) -> None:
        if actor != "user":
            raise SpaceError("only the authenticated user workflow can change question status")
        if status not in {"manual_handoff", "skipped", "open"}:
            raise SpaceError("unsupported question status")
        now = utc_now()
        with self.store.connect() as db:
            question = db.execute(
                "SELECT * FROM pending_questions WHERE id = ?",
                (question_id,),
            ).fetchone()
            if question is None:
                raise SpaceError(f"unknown question: {question_id}")
            db.execute(
                "UPDATE pending_questions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, question_id),
            )
            if status in {"manual_handoff", "skipped"} and question["application_id"]:
                app_state = "manual_handoff" if status == "manual_handoff" else "cancelled"
                db.execute(
                    "UPDATE applications SET state = ?, updated_at = ? WHERE id = ?",
                    (app_state, now, question["application_id"]),
                )
                db.execute(
                    """
                    INSERT INTO audit_events
                      (id, actor, event_type, subject_type, subject_id, details_json, created_at)
                    VALUES (?, ?, 'question_status_changed', 'question', ?, ?, ?)
                    """,
                    (
                        new_id("audit"),
                        actor,
                        question_id,
                        stable_json({"status": status, "reason": reason}),
                        now,
                    ),
                )

    def _compatibility_reason(
        self,
        *,
        answer: dict[str, Any],
        answer_scope: dict[str, Any],
        requested_context: dict[str, Any],
        required_context: dict[str, Any],
        expected_type: str | None,
        unit: str | None,
    ) -> str | None:
        if answer["reuse_permission"] == "this_application_only":
            if answer_scope.get("application_id") != requested_context.get("application_id"):
                return "application scope mismatch"
        elif answer["reuse_permission"] == "same_scope":
            if answer_scope != required_context:
                return "scope mismatch"
        elif answer["reuse_permission"] in {"global", "broader_scope"}:
            for key, value in answer_scope.items():
                if requested_context.get(key) != value:
                    return "broader scope mismatch"
        else:
            return "unsupported reuse permission"
        if expected_type is not None:
            value = _json_load(answer["typed_value_json"], None)
            if expected_type == "number" and not isinstance(value, int | float):
                return "type mismatch"
            if expected_type == "string" and not isinstance(value, str):
                return "type mismatch"
            if expected_type == "boolean" and not isinstance(value, bool):
                return "type mismatch"
        if unit is not None and answer["unit"] != unit:
            return "unit mismatch"
        return None

    def _is_stale(self, answer: dict[str, Any], semantic_key: str, now: datetime) -> bool:
        if answer["expires_at"]:
            return _parse_utc(answer["expires_at"]) <= now
        max_days = DEFAULT_FRESHNESS_DAYS.get(semantic_key)
        if max_days is None:
            return False
        created_at = _parse_utc(answer["created_at"])
        return created_at + timedelta(days=max_days) <= now

    def _unresolved(
        self,
        *,
        status: str,
        semantic_key: str,
        context: dict[str, Any],
        application_id: str | None,
        original_question: str | None,
        reason: str,
        suggested_reuse_scope: dict[str, Any] | None,
        create_question: bool,
        checkpoint: dict[str, Any] | None,
        candidates: tuple[str, ...],
        required_context: dict[str, Any],
    ) -> AnswerResolution:
        question_id = None
        if create_question:
            if application_id and checkpoint is not None:
                self._save_checkpoint_before_wait(application_id, checkpoint)
            field_context = {
                "semantic_key": semantic_key,
                "context": context,
                "original_question": original_question,
                "candidate_answer_ids": list(candidates),
                "resolution_status": status,
            }
            question_id = self.create_or_get_question(
                application_id=application_id,
                field_context=field_context,
                reason=reason,
                suggested_reuse_scope=suggested_reuse_scope or required_context,
            )
            if application_id:
                self._mark_needs_user_input(application_id)
        return AnswerResolution(
            status=status,
            answer_id=None,
            reason=reason,
            question_id=question_id,
            candidates=candidates,
            required_context=required_context,
        )

    def _save_checkpoint_before_wait(self, application_id: str, checkpoint: dict[str, Any]) -> None:
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO application_checkpoints
                  (id, application_id, stage, checkpoint_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    new_id("checkpoint"),
                    application_id,
                    str(checkpoint.get("stage", "preparing")),
                    stable_json(checkpoint),
                    utc_now(),
                ),
            )

    def _mark_needs_user_input(self, application_id: str) -> None:
        with self.store.connect() as db:
            current = db.execute(
                "SELECT state FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()
            if current is None or current["state"] in TERMINAL_APPLICATION_STATES:
                return
            db.execute(
                "UPDATE applications SET state = 'needs_user_input', updated_at = ? WHERE id = ?",
                (utc_now(), application_id),
            )

    def _resume_application(self, db: Any, application_id: str, answer_id: str, now: str) -> None:
        application = db.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if application is None or application["state"] in TERMINAL_APPLICATION_STATES:
            return
        checkpoint = db.execute(
            """
            SELECT stage FROM application_checkpoints
            WHERE application_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
        next_state = checkpoint["stage"] if checkpoint is not None else "preparing"
        if next_state == "needs_user_input":
            next_state = "preparing"
        snapshot = _json_load(application["answer_snapshot_json"], [])
        if answer_id not in snapshot:
            snapshot.append(answer_id)
        db.execute(
            """
            UPDATE applications
            SET state = ?, answer_snapshot_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_state, stable_json(snapshot), now, application_id),
        )
        db.execute(
            """
            INSERT INTO answer_snapshots
              (id, application_id, answer_ids_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (new_id("answersnapshot"), application_id, stable_json(snapshot), now),
        )
        db.execute(
            """
            INSERT INTO audit_events
              (id, actor, event_type, subject_type, subject_id, details_json, created_at)
            VALUES (?, 'user', 'answer_arrived_resume_required', 'application', ?, ?, ?)
            """,
            (
                new_id("audit"),
                application_id,
                stable_json({"answer_id": answer_id, "refresh_form_state": True}),
                now,
            ),
        )

    def _invalidate_answer_users(
        self,
        db: Any,
        old_answer_id: str,
        replacement_id: str,
        reason: str,
    ) -> None:
        for row in db.execute(
            """
            SELECT id, answer_snapshot_json FROM applications
            WHERE state NOT IN ('submitted','cancelled','permanent_failure')
            """
        ).fetchall():
            answer_ids = _json_load(row["answer_snapshot_json"], [])
            if old_answer_id not in answer_ids:
                continue
            db.execute(
                """
                INSERT INTO invalidation_events
                  (id, reason, affected_record_type, affected_record_id,
                   source_record_type, source_record_id, created_at)
                VALUES (?, ?, 'application', ?, 'reusable_answer', ?, ?)
                """,
                (
                    new_id("invalidate"),
                    reason,
                    row["id"],
                    replacement_id,
                    utc_now(),
                ),
            )
