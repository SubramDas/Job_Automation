"""Restricted in-process MCP facade for Phase 04.

The project treats these classes as server-side policy enforcement, not as prompt
instructions. Tools are synthetic/local only until later phases approve live integrations.
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.core.agents import AGENT_IDS, ALLOWED_TOOLS, AgentPackage
from app.core.config import ConfigError, _read_json
from app.core.contracts import ERROR_CODES
from app.discovery.manual_import import ManualJobImporter
from app.discovery.source_adapters import AdapterError, SearchQuery, build_adapter
from app.matching.evaluator import JobMatcher
from app.profile.onboarding import OnboardingService
from app.storage.space import SpaceError, SpaceStore, new_id, stable_json, utc_now
from app.tailoring.keyword_planning import (
    create_keyword_plan,
    save_keyword_plan,
)

MAX_TOOL_PAYLOAD_BYTES = 64 * 1024
MAX_TEXT_PAYLOAD_CHARS = 50_000
DEFAULT_DEADLINE_SECONDS = 5.0

ToolHandler = Callable[["ToolContext", dict[str, Any]], dict[str, Any]]

PHASE04_TOOL_NAMES: tuple[str, ...] = (
    "space.get_career_evidence",
    "space.get_search_profile",
    "space.get_application_facts",
    "space.resolve_answer",
    "jobs.search_sources",
    "jobs.fetch_description",
    "jobs.save_job",
    "jobs.get_job",
    "jobs.evaluate_match",
    "jobs.create_keyword_plan",
    "jobs.save_keyword_plan",
    "documents.get_artifact",
    "review.create_question",
    "review.get_question_status",
    "review.submit_package_for_review",
    "workflow.save_stage_result",
    "workflow.save_checkpoint",
    "workflow.get_assigned_task",
    "applications.inspect_form",
    "applications.fill_fields",
    "applications.attach_resume",
    "applications.read_back",
    "applications.request_submit",
    "applications.get_confirmation",
    "applications.reconcile_attempt",
)


class MCPError(ValueError):
    """Raised when a tool call violates the Phase 04 service contract."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown MCP error code: {code}")
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ToolSchema:
    name: str
    input_required: tuple[str, ...]
    output_fields: tuple[str, ...]
    mutates: str
    error_codes: tuple[str, ...]
    max_payload_bytes: int = MAX_TOOL_PAYLOAD_BYTES


@dataclass(frozen=True)
class ToolContext:
    agent_id: str
    task_id: str
    application_id: str | None = None
    assigned_job_ids: frozenset[str] = frozenset()
    assigned_artifact_ids: frozenset[str] = frozenset()
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    cancelled: bool = False


@dataclass(frozen=True)
class ToolCallRecord:
    tool_name: str
    agent_id: str
    status: str
    latency_ms: int
    input_hash: str
    output_hash: str | None
    error_code: str | None
    created_at: str


@dataclass
class RuntimeMetrics:
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_size(data: dict[str, Any]) -> int:
    return len(stable_json(data).encode("utf-8"))


def _require(args: dict[str, Any], required: tuple[str, ...], tool_name: str) -> None:
    missing = [key for key in required if key not in args]
    if missing:
        raise MCPError("schema_invalid", f"{tool_name} missing required inputs: {', '.join(missing)}")


def _sanitized_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, MCPError):
        return {"ok": False, "error": {"code": exc.code, "message": str(exc), "retryable": exc.retryable}}
    if isinstance(exc, SpaceError):
        return {"ok": False, "error": {"code": "schema_invalid", "message": str(exc), "retryable": False}}
    if isinstance(exc, AdapterError):
        return {"ok": False, "error": {"code": exc.code, "message": str(exc), "retryable": False}}
    return {"ok": False, "error": {"code": "schema_invalid", "message": "tool failed", "retryable": False}}


class ToolRegistry:
    """Policy-enforcing dispatcher for project MCP tool contracts."""

    def __init__(self) -> None:
        self._schemas: dict[str, ToolSchema] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self.metrics = RuntimeMetrics()

    def register(self, schema: ToolSchema, handler: ToolHandler) -> None:
        self._schemas[schema.name] = schema
        self._handlers[schema.name] = handler

    @property
    def schemas(self) -> dict[str, ToolSchema]:
        return dict(self._schemas)

    def call(self, context: ToolContext, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        input_hash = sha256_text(stable_json({"tool": tool_name, "args": args}))
        output_hash: str | None = None
        error_code: str | None = None
        status = "ok"
        try:
            if context.cancelled:
                raise MCPError("rate_limited", "tool call cancelled", retryable=True)
            if context.agent_id not in AGENT_IDS:
                raise MCPError("authorization_failed", "unknown agent identity")
            if tool_name not in ALLOWED_TOOLS[context.agent_id]:
                raise MCPError("authorization_failed", f"{context.agent_id} is not allowed to call {tool_name}")
            schema = self._schemas.get(tool_name)
            handler = self._handlers.get(tool_name)
            if schema is None or handler is None:
                raise MCPError("unsupported_source", f"tool is not implemented: {tool_name}")
            if _json_size(args) > schema.max_payload_bytes:
                raise MCPError("schema_invalid", "tool payload exceeds configured limit")
            _require(args, schema.input_required, tool_name)
            result = handler(context, args)
            response = {"ok": True, "tool": tool_name, "result": result}
            output_hash = sha256_text(stable_json(response))
            return response
        except Exception as exc:  # noqa: BLE001 - sanitize all tool boundary failures.
            status = "error"
            error_code = exc.code if isinstance(exc, MCPError) else "schema_invalid"
            return _sanitized_error(exc)
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            self.metrics.tool_calls.append(
                ToolCallRecord(
                    tool_name=tool_name,
                    agent_id=context.agent_id,
                    status=status,
                    latency_ms=latency_ms,
                    input_hash=input_hash,
                    output_hash=output_hash,
                    error_code=error_code,
                    created_at=utc_now(),
                )
            )


class Phase04Services:
    """Synthetic implementations for the Section 3 tool families."""

    def __init__(self, store: SpaceStore, project_root: Path) -> None:
        self.store = store
        self.project_root = project_root
        self.onboarding = OnboardingService(store)
        self.importer = ManualJobImporter(store)
        self.matcher = JobMatcher(store)
        self.sources = _read_json(project_root / "config" / "sources.example.json")
        self.policies = _read_json(project_root / "config" / "policies.example.json")

    def register_all(self, registry: ToolRegistry) -> None:
        definitions = (
            ("space.get_career_evidence", (), ("facts",), "none", self.get_career_evidence),
            ("space.get_search_profile", (), ("policy",), "none", self.get_search_profile),
            ("space.get_application_facts", ("application_id",), ("facts",), "none", self.get_application_facts),
            ("space.resolve_answer", ("semantic_key", "scope"), ("answer_id",), "none", self.resolve_answer),
            ("jobs.search_sources", ("source_id",), ("source", "status"), "none", self.search_sources),
            ("jobs.fetch_description", ("source_id", "url"), ("status",), "none", self.fetch_description),
            ("jobs.save_job", ("source_id", "url", "description"), ("job_id",), "local_db", self.save_job),
            ("jobs.get_job", ("job_id",), ("job", "description"), "none", self.get_job),
            ("jobs.evaluate_match", ("job_id",), ("decision",), "none", self.evaluate_match),
            ("jobs.create_keyword_plan", ("job_id",), ("status", "keyword_plan_artifact_id"), "local_artifact", self.create_keyword_plan),
            ("jobs.save_keyword_plan", ("job_id", "keywords"), ("status", "keyword_plan_artifact_id"), "local_artifact", self.save_keyword_plan),
            ("documents.get_artifact", ("artifact_id",), ("artifact",), "none", self.get_artifact),
            ("review.create_question", ("field_context", "reason"), ("question_id",), "review_queue", self.create_question),
            ("review.get_question_status", ("question_id",), ("question",), "none", self.get_question_status),
            ("review.submit_package_for_review", ("application_id", "package"), ("review_id",), "review_queue", self.submit_package_for_review),
            ("workflow.save_stage_result", ("stage", "result"), ("result_id",), "local_db", self.save_stage_result),
            ("workflow.save_checkpoint", ("application_id", "stage", "checkpoint"), ("checkpoint_id",), "local_db", self.save_checkpoint),
            ("workflow.get_assigned_task", (), ("task",), "none", self.get_assigned_task),
            ("applications.inspect_form", ("form_id",), ("fields",), "none", self.inspect_form),
            ("applications.fill_fields", ("form_id", "answers"), ("draft_id",), "local_draft", self.fill_fields),
            ("applications.attach_resume", ("draft_id", "artifact_id"), ("attachment",), "local_draft", self.attach_resume),
            ("applications.read_back", ("draft_id",), ("draft",), "none", self.read_back),
            ("applications.request_submit", ("application_id",), ("status",), "disabled", self.request_submit),
            ("applications.get_confirmation", ("attempt_id",), ("status",), "none", self.get_confirmation),
            ("applications.reconcile_attempt", ("attempt_id",), ("status",), "none", self.reconcile_attempt),
        )
        if tuple(item[0] for item in definitions) != PHASE04_TOOL_NAMES:
            raise ConfigError("Phase 04 tool definitions drifted from PHASE04_TOOL_NAMES")
        for name, required, output, mutates, handler in definitions:
            registry.register(
                ToolSchema(
                    name=name,
                    input_required=required,
                    output_fields=output,
                    mutates=mutates,
                    error_codes=ERROR_CODES,
                ),
                handler,
            )

    def get_career_evidence(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        rows = self._confirmed_facts(limit=100)
        redacted = [
            {
                "id": row["id"],
                "field_key": row["field_key"],
                "value_type": row["value_type"],
                "source_ref": row["source_ref"],
                "provenance": json.loads(row["provenance_json"]),
                "version": row["version"],
            }
            for row in rows
        ]
        return {"facts": redacted}

    def get_search_profile(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute(
                """
                SELECT version, hard_constraints_json, weighted_preferences_json, exclusions_json
                FROM preference_policies ORDER BY version DESC LIMIT 1
                """
            ).fetchone()
        if row is None:
            return {"policy": None, "status": "missing_policy"}
        return {
            "policy": {
                "version": row["version"],
                "hard_constraints": json.loads(row["hard_constraints_json"]),
                "weighted_preferences": json.loads(row["weighted_preferences_json"]),
                "exclusions": json.loads(row["exclusions_json"]),
            }
        }

    def get_application_facts(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        self._require_application_scope(context, args["application_id"])
        rows = self._confirmed_facts(limit=100)
        return {
            "facts": [
                {
                    "id": row["id"],
                    "field_key": row["field_key"],
                    "value_type": row["value_type"],
                    "sensitivity": row["sensitivity"],
                    "version": row["version"],
                }
                for row in rows
            ]
        }

    def resolve_answer(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        result = self.onboarding.resolve_answer(
            semantic_key=args["semantic_key"],
            context=args["scope"],
            expected_type=args.get("expected_type"),
            unit=args.get("unit"),
            application_id=context.application_id,
            original_question=args.get("original_question"),
            create_question=bool(args.get("create_question", False)),
            reason=args.get("reason"),
            suggested_reuse_scope=args.get("suggested_reuse_scope"),
            checkpoint=args.get("checkpoint"),
        )
        return {
            "answer_id": result.answer_id,
            "status": result.status,
            "reason": result.reason,
            "question_id": result.question_id,
            "candidate_answer_ids": list(result.candidates),
            "required_context": result.required_context,
        }

    def search_sources(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        source = self._source(args["source_id"])
        if "discovery" not in source["capabilities"]:
            raise MCPError("unsupported_source", "source does not support discovery in this phase")
        if "fixture" not in source["capabilities"] and "api_candidate" not in source["capabilities"]:
            return {"source": self._source_public(source), "status": "manual_import_only", "results": []}
        adapter = build_adapter(source)
        results = adapter.search(
            SearchQuery(
                text=str(args.get("query", "")),
                locations=tuple(args.get("locations", ())),
                work_modes=tuple(args.get("work_modes", ())),
                employment_type=args.get("employment_type"),
                max_results=int(args.get("max_results", 10)),
            )
        )
        return {
            "source": self._source_public(source),
            "status": "searched",
            "results": [result.__dict__ for result in results],
        }

    def fetch_description(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        source = self._source(args["source_id"])
        if "fixture" in source["capabilities"] or "api_candidate" in source["capabilities"]:
            adapter = build_adapter(source)
            description = adapter.fetch_description(
                url=args["url"],
                source_job_id=args.get("source_job_id"),
            )
            return {
                "status": "description_retrieved",
                "source_id": description.source_id,
                "source_job_id": description.source_job_id,
                "url": description.url,
                "description": description.description,
                "application_destination": description.application_destination,
                "retrieved_via": description.retrieved_via,
            }
        if source["id"] != "manual_import":
            raise MCPError("unsupported_source", "live description retrieval is unavailable in Phase 04")
        return {"status": "requires_manual_description", "url": args["url"]}

    def save_job(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        source = self._source(args["source_id"])
        if "description_retrieval" not in source["capabilities"]:
            raise MCPError("unsupported_source", "source does not support saving retrieved descriptions")
        result = self.importer.import_job(
            source_id=args["source_id"],
            url=args.get("url"),
            description=str(args["description"]),
        )
        return {
            "job_id": result.job_id,
            "description_hash": result.description_hash,
            "snapshot_artifact_id": result.snapshot_artifact_id,
            "extraction_id": result.extraction_id,
            "duplicate_signals": result.duplicate_signals,
            "extraction": result.extraction,
        }

    def get_job(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        job_id = args["job_id"]
        if context.assigned_job_ids and job_id not in context.assigned_job_ids:
            raise MCPError("authorization_failed", "job is outside this task scope")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            extraction = db.execute(
                "SELECT * FROM job_extractions WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            match = db.execute(
                "SELECT * FROM match_results WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            artifact = db.execute(
                "SELECT * FROM artifacts WHERE id = ? ORDER BY version DESC LIMIT 1",
                (row["snapshot_artifact_id"],) if row is not None else ("",),
            ).fetchone()
        if row is None:
            raise MCPError("missing_fact", "unknown job id")
        description = ""
        if artifact is not None:
            description = Path(artifact["storage_path"]).read_text(encoding="utf-8")
        payload = {"job": dict(row), "description": description}
        if extraction is not None:
            payload["extraction"] = {
                "id": extraction["id"],
                "record": json.loads(extraction["extraction_json"]),
                "warnings": json.loads(extraction["warnings_json"]),
                "unknown_fields": json.loads(extraction["unknown_fields_json"]),
            }
        if match is not None:
            payload["latest_match"] = {
                "id": match["id"],
                "decision": match["decision"],
                "score": match["score"],
                "coverage": json.loads(match["coverage_json"]),
                "review_reasons": json.loads(match["review_reasons_json"]),
            }
        return payload

    def evaluate_match(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        job_id = args["job_id"]
        if context.assigned_job_ids and job_id not in context.assigned_job_ids:
            raise MCPError("authorization_failed", "job is outside this task scope")
        result = self.matcher.evaluate(job_id)
        return {
            "decision": result.decision,
            "match_result_id": result.match_result_id,
            "handoff_id": result.handoff_id,
            "score": result.score,
            "coverage": result.coverage,
            "review_reasons": result.review_reasons,
        }

    def create_keyword_plan(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        job_id = args["job_id"]
        if context.assigned_job_ids and job_id not in context.assigned_job_ids:
            raise MCPError("authorization_failed", "job is outside this task scope")
        result = create_keyword_plan(self.store, project_root=self.project_root, job_id=job_id)
        return self._keyword_plan_response(result)

    def save_keyword_plan(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        job_id = args["job_id"]
        if context.assigned_job_ids and job_id not in context.assigned_job_ids:
            raise MCPError("authorization_failed", "job is outside this task scope")
        result = save_keyword_plan(
            self.store,
            job_id=job_id,
            keywords=args["keywords"],
            warnings=args.get("warnings"),
            model=args.get("model"),
            prompt_version=args.get("prompt_version", "agent-a-keyword-plan-v1"),
        )
        return self._keyword_plan_response(result)

    def _keyword_plan_response(self, result: Any) -> dict[str, Any]:
        return {
            "status": result.status,
            "job_id": result.job_id,
            "keyword_plan_id": result.keyword_plan_id,
            "keyword_plan_artifact_id": result.artifact.artifact_id,
            "keyword_plan_sha256": result.artifact.sha256,
            "content_type": result.artifact.content_type,
            "priority_counts": result.plan["priority_counts"],
            "mandate_counts": result.plan["mandate_counts"],
            "keywords": result.plan["keywords"],
            "warnings": result.plan["warnings"],
            "validation": result.validation,
            "model": result.plan["model"],
        }

    def get_artifact(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        artifact = self._artifact(args["artifact_id"], context)
        return {
            "artifact": {
                "id": artifact["id"],
                "version": artifact["version"],
                "sha256": artifact["sha256"],
                "content_type": artifact["content_type"],
                "size_bytes": artifact["size_bytes"],
                "owner": artifact["owner"],
                "created_at": artifact["created_at"],
            }
        }

    def create_question(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        question_id = self.onboarding.create_pending_question(
            application_id=context.application_id,
            field_context=args["field_context"],
            reason=args["reason"],
            suggested_reuse_scope=args.get("suggested_reuse_scope"),
        )
        return {"question_id": question_id, "status": "open"}

    def get_question_status(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id, application_id, status, answer_ref FROM pending_questions WHERE id = ?",
                (args["question_id"],),
            ).fetchone()
        if row is None:
            raise MCPError("missing_fact", "unknown question id")
        if row["application_id"] and context.application_id and row["application_id"] != context.application_id:
            raise MCPError("authorization_failed", "question is outside this application scope")
        return {"question": dict(row)}

    def submit_package_for_review(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        self._require_application_scope(context, args["application_id"])
        review_id = self.onboarding.create_pending_question(
            application_id=args["application_id"],
            field_context={"review_package_hash": sha256_text(stable_json(args["package"]))},
            reason="application package requires user review",
            suggested_reuse_scope=None,
        )
        return {"review_id": review_id, "status": "needs_review"}

    def save_stage_result(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        result_id = new_id("stage")
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO audit_events
                  (id, actor, event_type, subject_type, subject_id, details_json, created_at)
                VALUES (?, ?, 'stage_result', 'task', ?, ?, ?)
                """,
                (
                    result_id,
                    context.agent_id,
                    context.task_id,
                    stable_json({"stage": args["stage"], "result_hash": sha256_text(stable_json(args["result"]))}),
                    utc_now(),
                ),
            )
        return {"result_id": result_id}

    def save_checkpoint(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        self._require_application_scope(context, args["application_id"])
        checkpoint_id = self.onboarding.save_checkpoint(
            application_id=args["application_id"],
            stage=args["stage"],
            checkpoint=args["checkpoint"],
        )
        return {"checkpoint_id": checkpoint_id}

    def get_assigned_task(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "task": {
                "task_id": context.task_id,
                "application_id": context.application_id,
                "assigned_job_ids": sorted(context.assigned_job_ids),
                "assigned_artifact_ids": sorted(context.assigned_artifact_ids),
            }
        }

    def inspect_form(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        if not str(args["form_id"]).startswith("synthetic_"):
            raise MCPError("unsupported_form", "only synthetic forms are supported in Phase 04")
        return {
            "fields": [
                {"id": "email", "semantic_key": "contact.email", "required": True, "type": "email"},
                {"id": "resume", "semantic_key": "document.resume", "required": True, "type": "file"},
            ],
            "submit_available": False,
        }

    def fill_fields(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        if not str(args["form_id"]).startswith("synthetic_"):
            raise MCPError("unsupported_form", "only synthetic forms are supported in Phase 04")
        return {"draft_id": new_id("draft"), "status": "filled_local_draft", "answer_count": len(args["answers"])}

    def attach_resume(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        artifact = self._artifact(args["artifact_id"], context)
        return {"attachment": {"draft_id": args["draft_id"], "artifact_id": artifact["id"], "sha256": artifact["sha256"]}}

    def read_back(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {"draft": {"draft_id": args["draft_id"], "status": "local_draft_only"}}

    def request_submit(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        raise MCPError("external_action_disabled", "live submission is unavailable until Phase 11")

    def get_confirmation(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {"status": "no_live_attempts_in_phase04", "attempt_id": args["attempt_id"]}

    def reconcile_attempt(self, context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {"status": "manual_review_required", "attempt_id": args["attempt_id"], "retry_safe": False}

    def _confirmed_facts(self, *, limit: int) -> list[Any]:
        with self.store.connect() as db:
            return db.execute(
                """
                SELECT id, field_key, value_type, value_json, source_ref, provenance_json,
                       confirmation_state, sensitivity, version
                FROM candidate_facts
                WHERE confirmation_state = 'confirmed'
                ORDER BY field_key, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def _source(self, source_id: str) -> dict[str, Any]:
        for source in self.sources["sources"]:
            if source["id"] == source_id:
                return source
        raise MCPError("unsupported_source", f"unknown source: {source_id}")

    def _source_public(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": source["id"],
            "name": source["name"],
            "status": source["status"],
            "capabilities": source["capabilities"],
            "live_external_actions": source["live_external_actions"],
        }

    def _artifact(self, artifact_id: str, context: ToolContext) -> dict[str, Any]:
        if context.assigned_artifact_ids and artifact_id not in context.assigned_artifact_ids:
            raise MCPError("authorization_failed", "artifact is outside this task scope")
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM artifacts WHERE id = ? ORDER BY version DESC LIMIT 1",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise MCPError("missing_fact", "unknown artifact id")
        return dict(row)

    def _require_application_scope(self, context: ToolContext, application_id: str) -> None:
        if context.application_id is not None and application_id != context.application_id:
            raise MCPError("authorization_failed", "application is outside this task scope")


def build_phase04_registry(store: SpaceStore, project_root: Path) -> ToolRegistry:
    registry = ToolRegistry()
    Phase04Services(store, project_root).register_all(registry)
    return registry


def validate_phase04_tool_coverage(packages: tuple[AgentPackage, ...], registry: ToolRegistry) -> None:
    implemented = set(registry.schemas) if registry.schemas else set(PHASE04_TOOL_NAMES)
    for package in packages:
        missing = set(ALLOWED_TOOLS[package.agent_id]) - implemented
        if missing:
            raise ConfigError(f"{package.agent_id} has unimplemented Phase 04 tools: {sorted(missing)}")


def _extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as docx:
            xml = docx.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return ""
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return "\n".join(node.text for node in root.findall(".//w:t", namespace) if node.text)
