"""Codex stdio MCP server for Agent B job discovery.

This wrapper exposes a compact tool surface to Codex:

- ``agent_b_fetch_jobs`` runs read-only discovery and writes review files.
- ``agent_b_preview_search`` shows the query plan without live source calls.
- ``agent_b_rebuild_review_workspace`` regenerates readable files from Space.
- ``agent_b_get_review_index`` reads the generated review index.
- ``agent_b_list_saved_jobs`` returns a lightweight saved-job list.
- ``agent_b_import_job_text`` imports pasted job details and a source/apply link.
- ``agent_b_fetch_job_url`` imports content already retrieved through Fetch MCP.

The server delegates discovery, policy checks, storage, and matching to the existing
Agent B runner and project MCP facade.
"""

from __future__ import annotations

import ipaddress
import html as html_lib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.core.env import load_env_file
from app.discovery.agent_b_run import run_agent_b_discovery
from app.discovery.job_review_workspace import rebuild_job_review_workspace, review_root
from app.mcp.runtime import ToolContext, build_phase04_registry
from app.storage.space import SpacePaths, SpaceStore, utc_now

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - exercised when SDK is absent locally.
    FastMCP = None  # type: ignore[assignment]

SERVER_NAME = "job-automation-agent-b"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
AUTO_SOURCE_SENTINEL = "auto"
FETCH_MCP_SOURCE_ID = "fetch_mcp_url_import"
MIN_FETCHED_JOB_TEXT_CHARS = 120


AGENT_B_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "agent_b_fetch_jobs",
        "description": (
            "Run Agent B read-only job discovery, save matched jobs locally, and return "
            "a concise summary with review workspace paths and pending Agent A MCP handoffs. "
            "For each pending handoff, Codex must call Agent A MCP to generate and save keywords."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional source IDs. Omit or pass ['auto'] to use every configured "
                        "enabled read-only source."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "description": "Maximum results per source.",
                },
                "include_jobspy": {
                    "type": "boolean",
                    "description": "Append the local JobSpy MCP-backed source when configured/running.",
                },
            },
        },
    },
    {
        "name": "agent_b_preview_search",
        "description": "Build Agent B's query plan without calling external job sources.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sources": {"type": "array", "items": {"type": "string"}},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 25},
                "include_jobspy": {"type": "boolean"},
            },
        },
    },
    {
        "name": "agent_b_rebuild_review_workspace",
        "description": "Regenerate private/job_reviews from already saved Space jobs without live search.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "agent_b_get_review_index",
        "description": "Read the generated Agent B review index markdown.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "agent_b_list_saved_jobs",
        "description": "List saved jobs from Space without returning full job descriptions.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "name": "agent_b_import_job_text",
        "description": (
            "Import a pasted job description and job/apply link, then save, extract, match, "
            "and mirror it into the private review workspace. A successful import returns an "
            "Agent A MCP handoff that Codex must complete before calling the workflow finished."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["url", "description"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Original job or apply link supplied by the user.",
                },
                "description": {
                    "type": "string",
                    "description": "Full pasted job description/details text.",
                },
                "source_id": {
                    "type": "string",
                    "description": "Optional project source ID. Defaults to manual_import.",
                },
            },
        },
    },
    {
        "name": "agent_b_fetch_job_url",
        "description": (
            "Import a public job URL after Codex retrieves it with Fetch MCP. Call Fetch MCP "
            "first, then pass the fetched markdown/text here so Agent B can save, extract, "
            "match, dedupe, and mirror it into the private review workspace. A successful "
            "import returns an Agent A MCP handoff that Codex must complete."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["url", "fetched_text"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Original public job URL supplied by the user.",
                },
                "fetched_text": {
                    "type": "string",
                    "description": "Markdown/text returned by Fetch MCP for the job page.",
                },
                "final_url": {
                    "type": "string",
                    "description": "Final URL after redirects, if Fetch MCP reports one.",
                },
                "content_truncated": {
                    "type": "boolean",
                    "description": "Whether the Fetch MCP response was truncated.",
                },
                "fetch_warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Warnings from the Fetch MCP step, if any.",
                },
            },
        },
    },
)


class AgentBServer:
    def __init__(self, project_root: Path, space_paths: SpacePaths | None = None) -> None:
        self.project_root = project_root.resolve()
        load_env_file(self.project_root)
        self.store = SpaceStore(space_paths or SpacePaths.from_project_root(self.project_root))
        self.store.migrate()
        self.space_paths = self.store.paths
        self.registry = build_phase04_registry(self.store, self.project_root)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if request.get("jsonrpc") != "2.0":
            return _error_response(request.get("id"), -32600, "Invalid JSON-RPC version")
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            self._handle_notification(method, request.get("params") or {})
            return None
        try:
            if method == "initialize":
                result = self._initialize(request.get("params") or {})
            elif method == "tools/list":
                result = {"tools": list(AGENT_B_TOOLS)}
            elif method == "tools/call":
                result = self._call_tool(request.get("params") or {})
            elif method == "ping":
                result = {}
            else:
                return _error_response(request_id, -32601, f"Unknown method: {method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - MCP boundary must never leak tracebacks.
            return _error_response(request_id, -32000, str(exc))

    def _handle_notification(self, method: str | None, params: dict[str, Any]) -> None:
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return
        _log(f"ignored notification: {method} {params!r}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "agent_b_fetch_jobs":
            result = self.fetch_jobs(
                sources=_sources(arguments),
                max_results=_max_results(arguments),
                include_jobspy=bool(arguments.get("include_jobspy", False)),
            )
        elif name == "agent_b_preview_search":
            result = self.preview_search(
                sources=_sources(arguments),
                max_results=_max_results(arguments),
                include_jobspy=bool(arguments.get("include_jobspy", False)),
            )
        elif name == "agent_b_rebuild_review_workspace":
            result = self.rebuild_review_workspace()
        elif name == "agent_b_get_review_index":
            result = self.get_review_index()
        elif name == "agent_b_list_saved_jobs":
            result = self.list_saved_jobs(limit=_limit(arguments))
        elif name == "agent_b_import_job_text":
            result = self.import_job_text(
                url=_required_str(arguments, "url"),
                description=_required_str(arguments, "description"),
                source_id=str(arguments.get("source_id") or "manual_import").strip() or "manual_import",
            )
        elif name == "agent_b_fetch_job_url":
            result = self.import_fetched_job_url(
                url=_required_str(arguments, "url"),
                fetched_text=_required_str(arguments, "fetched_text"),
                final_url=_optional_str(arguments, "final_url"),
                content_truncated=bool(arguments.get("content_truncated", False)),
                fetch_warnings=_string_list(arguments.get("fetch_warnings", []), "fetch_warnings"),
            )
        else:
            raise ValueError(f"unknown tool: {name}")
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2, sort_keys=True)}],
            "structuredContent": result,
            "isError": False,
        }

    def fetch_jobs(
        self,
        *,
        sources: list[str] | None = None,
        max_results: int = 10,
        include_jobspy: bool = False,
    ) -> dict[str, Any]:
        run_sources, skipped_sources = _resolved_sources(
            self.project_root,
            sources,
            include_jobspy=include_jobspy,
        )
        result = run_agent_b_discovery(
            project_root=self.project_root,
            sources=run_sources,
            max_results=max_results,
            space_paths=self.space_paths,
        )
        for row in result.rows:
            job_id = row.get("job_id")
            if not job_id or row.get("description_status") in {"unavailable", "save_failed"}:
                continue
            row["agent_a_handoff"] = self._agent_a_handoff(job_id)
        return _run_payload(result, sources=run_sources, skipped_sources=skipped_sources)

    def preview_search(
        self,
        *,
        sources: list[str] | None = None,
        max_results: int = 10,
        include_jobspy: bool = False,
    ) -> dict[str, Any]:
        run_sources, skipped_sources = _resolved_sources(
            self.project_root,
            sources,
            include_jobspy=include_jobspy,
        )
        result = run_agent_b_discovery(
            project_root=self.project_root,
            sources=run_sources,
            max_results=max_results,
            preview=True,
            space_paths=self.space_paths,
        )
        return _run_payload(result, sources=run_sources, skipped_sources=skipped_sources)

    def rebuild_review_workspace(self) -> dict[str, Any]:
        result = rebuild_job_review_workspace(self.store)
        return {
            "status": "completed",
            "root": str(result.root),
            "index_path": str(result.index_path),
            "job_count": len(result.job_paths),
        }

    def get_review_index(self) -> dict[str, Any]:
        index_path = review_root(self.store) / "index.md"
        if not index_path.exists():
            return {
                "status": "missing",
                "index_path": str(index_path),
                "content": "",
                "message": "Review index has not been generated yet.",
            }
        return {
            "status": "available",
            "index_path": str(index_path),
            "content": index_path.read_text(encoding="utf-8"),
        }

    def list_saved_jobs(self, *, limit: int = 25) -> dict[str, Any]:
        with self.store.connect() as db:
            rows = db.execute(
                """
                SELECT
                  jobs.id,
                  jobs.title,
                  jobs.employer,
                  jobs.canonical_url,
                  jobs.status,
                  jobs.description_hash,
                  jobs.snapshot_artifact_id,
                  jobs.retrieved_at,
                  jobs.created_at,
                  match_results.score,
                  match_results.decision
                FROM jobs
                LEFT JOIN match_results ON match_results.id = (
                  SELECT id FROM match_results mr
                  WHERE mr.job_id = jobs.id
                  ORDER BY mr.created_at DESC, mr.rowid DESC
                  LIMIT 1
                )
                ORDER BY jobs.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        jobs = []
        root = review_root(self.store)
        for row in rows:
            job = dict(row)
            job["review_path"] = _review_path_for_saved_job(root, job)
            jobs.append(job)
        return {"status": "completed", "count": len(jobs), "jobs": jobs}

    def import_job_text(self, *, url: str, description: str, source_id: str = "manual_import") -> dict[str, Any]:
        context = ToolContext(agent_id="agent_b_discovery", task_id="codex_agent_b_import_job_text")
        saved = self.registry.call(
            context,
            "jobs.save_job",
            {
                "source_id": source_id,
                "url": url,
                "description": description,
            },
        )
        if not saved["ok"]:
            error = saved["error"]
            raise ValueError(f"{error['code']}: {error['message']}")
        job_id = saved["result"]["job_id"]
        scoped = ToolContext(
            agent_id="agent_b_discovery",
            task_id="codex_agent_b_import_job_text",
            assigned_job_ids=frozenset({job_id}),
        )
        matched = self.registry.call(scoped, "jobs.evaluate_match", {"job_id": job_id})
        if not matched["ok"]:
            error = matched["error"]
            raise ValueError(f"{error['code']}: {error['message']}")
        job = self.registry.call(scoped, "jobs.get_job", {"job_id": job_id})
        if not job["ok"]:
            error = job["error"]
            raise ValueError(f"{error['code']}: {error['message']}")
        review = rebuild_job_review_workspace(self.store)
        job_result = job["result"]
        match_result = matched["result"]
        review_path = review.job_paths.get(job_id)
        result = {
            "status": "imported",
            "source_id": source_id,
            "job_id": job_id,
            "title": job_result["job"].get("title"),
            "company": job_result["job"].get("employer"),
            "canonical_url": job_result["job"].get("canonical_url"),
            "decision": match_result.get("decision"),
            "score": match_result.get("score"),
            "coverage": match_result.get("coverage"),
            "review_reasons": match_result.get("review_reasons", []),
            "description_hash": saved["result"].get("description_hash"),
            "snapshot_artifact_id": saved["result"].get("snapshot_artifact_id"),
            "duplicate_signals": saved["result"].get("duplicate_signals", []),
            "review_workspace_index": str(review.index_path),
            "review_path": str(review_path) if review_path is not None else None,
            "unknown_fields": job_result.get("extraction", {}).get("unknown_fields", []),
            "warnings": job_result.get("extraction", {}).get("warnings", []),
        }
        result["agent_a_handoff"] = self._agent_a_handoff(job_id)
        return result

    def _agent_a_handoff(self, job_id: str) -> dict[str, Any]:
        """Return a durable Codex-to-Agent-A MCP delegation for one saved snapshot."""
        with self.store.connect() as db:
            job = db.execute(
                "SELECT description_hash FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if job is None:
                return {"status": "error", "message": f"unknown job id: {job_id}"}
            existing = db.execute(
                """
                SELECT id, artifact_id, artifact_sha256, model_json
                FROM job_keyword_plans
                WHERE job_id = ? AND description_hash = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (job_id, job["description_hash"]),
            ).fetchone()
        existing_model = json.loads(existing["model_json"]) if existing is not None else {}
        if existing is not None and existing_model.get("provider_mode") == "codex_mcp":
            return {
                "status": "already_available",
                "job_id": job_id,
                "keyword_plan_id": existing["id"],
                "keyword_plan_artifact_id": existing["artifact_id"],
                "keyword_plan_sha256": existing["artifact_sha256"],
            }
        return {
            "status": "pending_codex_mcp",
            "job_id": job_id,
            "description_hash": job["description_hash"],
            "mcp_server": "jobAutomationAgentA",
            "steps": [
                "Call agent_a_get_job with job_id.",
                "Use the current Codex session model to create the ranked keyword plan from that description only.",
                "Call agent_a_save_keyword_plan with job_id, keywords, warnings, and Codex model metadata.",
            ],
            "supersedes_keyword_plan_id": existing["id"] if existing is not None else None,
        }

    def import_fetched_job_url(
        self,
        *,
        url: str,
        fetched_text: str,
        final_url: str | None = None,
        content_truncated: bool = False,
        fetch_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        requested_url = _validate_public_job_url(url, label="url")
        resolved_url = _validate_public_job_url(final_url, label="final_url") if final_url else requested_url
        warnings = list(fetch_warnings or [])
        normalized_text, normalization_warnings = _normalize_fetched_job_text(fetched_text, resolved_url)
        warnings.extend(normalization_warnings)
        provenance = {
            "requested_url": requested_url,
            "final_url": resolved_url,
            "source_id": FETCH_MCP_SOURCE_ID,
            "fetched_at": utc_now(),
            "content_length": len(fetched_text),
            "normalized_content_length": len(normalized_text),
            "content_truncated": bool(content_truncated),
            "fetch_warnings": warnings,
        }
        handoff_reason = _fetched_text_handoff_reason(normalized_text)
        if handoff_reason is not None:
            return {
                "status": "manual_handoff",
                "source_id": FETCH_MCP_SOURCE_ID,
                "requested_url": requested_url,
                "final_url": resolved_url,
                "reason": handoff_reason,
                "provenance": provenance,
                "message": (
                    "Fetch MCP did not return a usable job description. Paste the full JD text "
                    "with the link and use agent_b_import_job_text."
                ),
            }
        result = self.import_job_text(
            url=resolved_url,
            description=normalized_text,
            source_id=FETCH_MCP_SOURCE_ID,
        )
        if _fetch_import_needs_refresh(self.store, result, normalized_text, resolved_url):
            result = self._refresh_fetched_job_snapshot(
                job_id=result["job_id"],
                url=resolved_url,
                description=normalized_text,
            )
        result["agent_a_handoff"] = self._agent_a_handoff(result["job_id"])
        _record_fetch_import_audit(self.store, result["job_id"], provenance)
        result.update(
            {
                "status": "imported",
                "source_id": FETCH_MCP_SOURCE_ID,
                "requested_url": requested_url,
                "final_url": resolved_url,
                "fetch_provenance": provenance,
            }
        )
        return result

    def _refresh_fetched_job_snapshot(self, *, job_id: str, url: str, description: str) -> dict[str, Any]:
        from app.discovery.manual_import import (
            description_hash,
            evidence_map,
            extract_job_description,
            normalized_job_identity,
        )
        from app.storage.space import new_id, stable_json

        text = description.strip()
        digest = description_hash(text)
        extracted = extract_job_description(text, canonical_url=url)
        now = utc_now()
        with self.store.connect() as db:
            current_job = db.execute(
                "SELECT description_hash, snapshot_artifact_id FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if current_job is not None and current_job["description_hash"] == digest:
            snapshot_artifact_id = current_job["snapshot_artifact_id"]
        else:
            artifact = self.store.artifacts.put_bytes(
                text.encode("utf-8"),
                filename="job-description.txt",
                content_type="text/plain",
                owner="jobs",
                artifact_id=new_id("jobdesc"),
            )
            self.store.record_artifact(artifact)
            snapshot_artifact_id = artifact.artifact_id
        with self.store.connect() as db:
            db.execute(
                """
                UPDATE jobs
                SET employer = ?,
                    requisition_id = ?,
                    title = ?,
                    normalized_identity = ?,
                    description_hash = ?,
                    retrieved_at = ?,
                    status = 'extracted',
                    snapshot_artifact_id = ?
                WHERE id = ?
                """,
                (
                    extracted["company"]["value"],
                    extracted["requisition_id"]["value"],
                    extracted["title"]["value"],
                    normalized_job_identity(extracted, url, digest),
                    digest,
                    now,
                    snapshot_artifact_id,
                    job_id,
                ),
            )
            extraction_id = new_id("jobextract")
            db.execute(
                """
                INSERT INTO job_extractions
                  (id, job_id, extraction_json, evidence_json, warnings_json,
                   unknown_fields_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction_id,
                    job_id,
                    stable_json(extracted),
                    stable_json(evidence_map(extracted)),
                    stable_json(extracted["warnings"]),
                    stable_json(extracted["unknown_fields"]),
                    now,
                ),
            )
            db.execute(
                """
                INSERT INTO audit_events
                  (id, actor, event_type, subject_type, subject_id, details_json, created_at)
                VALUES (?, 'agent_b_discovery', 'job_fetch_mcp_snapshot_refreshed', 'job', ?, ?, ?)
                """,
                (
                    new_id("audit"),
                    job_id,
                    stable_json(
                        {
                            "source_id": FETCH_MCP_SOURCE_ID,
                            "description_hash": digest,
                            "snapshot_artifact_id": snapshot_artifact_id,
                            "extraction_id": extraction_id,
                        }
                    ),
                    now,
                ),
            )
        scoped = ToolContext(
            agent_id="agent_b_discovery",
            task_id="codex_agent_b_fetch_job_url_refresh",
            assigned_job_ids=frozenset({job_id}),
        )
        matched = self.registry.call(scoped, "jobs.evaluate_match", {"job_id": job_id})
        if not matched["ok"]:
            error = matched["error"]
            raise ValueError(f"{error['code']}: {error['message']}")
        job = self.registry.call(scoped, "jobs.get_job", {"job_id": job_id})
        if not job["ok"]:
            error = job["error"]
            raise ValueError(f"{error['code']}: {error['message']}")
        review = rebuild_job_review_workspace(self.store)
        job_result = job["result"]
        match_result = matched["result"]
        review_path = review.job_paths.get(job_id)
        return {
            "status": "imported",
            "source_id": FETCH_MCP_SOURCE_ID,
            "job_id": job_id,
            "title": job_result["job"].get("title"),
            "company": job_result["job"].get("employer"),
            "canonical_url": job_result["job"].get("canonical_url"),
            "decision": match_result.get("decision"),
            "score": match_result.get("score"),
            "coverage": match_result.get("coverage"),
            "review_reasons": match_result.get("review_reasons", []),
            "description_hash": digest,
            "snapshot_artifact_id": snapshot_artifact_id,
            "duplicate_signals": [{"signal_type": "canonical_url", "risk": "exact", "matched_job_id": job_id}],
            "review_workspace_index": str(review.index_path),
            "review_path": str(review_path) if review_path is not None else None,
            "unknown_fields": job_result.get("extraction", {}).get("unknown_fields", []),
            "warnings": job_result.get("extraction", {}).get("warnings", []),
            "refreshed_existing_job": True,
        }


def build_fastmcp_server(project_root: Path | None = None) -> Any:
    if FastMCP is None:
        raise RuntimeError("The official MCP SDK is not installed. Use .venv-mcp/bin/python or install mcp.")
    agent_server = AgentBServer(project_root or _project_root())
    server = FastMCP(
        SERVER_NAME,
        instructions=(
            "Agent B job discovery tools. Use agent_b_fetch_jobs for read-only discovery. "
            "Jobs and descriptions are stored locally under private Space and private/job_reviews. "
            "Never submit applications."
        ),
    )

    @server.tool(
        name="agent_b_fetch_jobs",
        description=(
            "Run read-only Agent B job discovery and save reviewable jobs locally. Complete "
            "each returned pending Agent A MCP handoff before reporting the workflow finished."
        ),
    )
    def agent_b_fetch_jobs(
        sources: list[str] | None = None,
        max_results: int = 10,
        include_jobspy: bool = False,
    ) -> dict[str, Any]:
        return agent_server.fetch_jobs(
            sources=sources,
            max_results=max_results,
            include_jobspy=include_jobspy,
        )

    @server.tool(
        name="agent_b_preview_search",
        description="Build Agent B's query plan without calling external job sources.",
    )
    def agent_b_preview_search(
        sources: list[str] | None = None,
        max_results: int = 10,
        include_jobspy: bool = False,
    ) -> dict[str, Any]:
        return agent_server.preview_search(
            sources=sources,
            max_results=max_results,
            include_jobspy=include_jobspy,
        )

    @server.tool(
        name="agent_b_rebuild_review_workspace",
        description="Regenerate private/job_reviews from already saved Space jobs without live search.",
    )
    def agent_b_rebuild_review_workspace() -> dict[str, Any]:
        return agent_server.rebuild_review_workspace()

    @server.tool(
        name="agent_b_get_review_index",
        description="Read the generated Agent B review index markdown.",
    )
    def agent_b_get_review_index() -> dict[str, Any]:
        return agent_server.get_review_index()

    @server.tool(
        name="agent_b_list_saved_jobs",
        description="List saved jobs from Space without returning full descriptions.",
    )
    def agent_b_list_saved_jobs(limit: int = 25) -> dict[str, Any]:
        return agent_server.list_saved_jobs(limit=limit)

    @server.tool(
        name="agent_b_import_job_text",
        description=(
            "Import pasted job text and a job/apply link, then save, extract, match, and "
            "mirror it locally. Complete the returned Agent A MCP handoff with Codex."
        ),
    )
    def agent_b_import_job_text(
        url: str,
        description: str,
        source_id: str = "manual_import",
    ) -> dict[str, Any]:
        return agent_server.import_job_text(url=url, description=description, source_id=source_id)

    @server.tool(
        name="agent_b_fetch_job_url",
        description=(
            "Import content fetched from a public job URL. Codex should call Fetch MCP first "
            "and pass the fetched markdown/text to this tool, then complete the returned "
            "Agent A MCP handoff with the current Codex session model."
        ),
    )
    def agent_b_fetch_job_url(
        url: str,
        fetched_text: str,
        final_url: str | None = None,
        content_truncated: bool = False,
        fetch_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        return agent_server.import_fetched_job_url(
            url=url,
            fetched_text=fetched_text,
            final_url=final_url,
            content_truncated=content_truncated,
            fetch_warnings=fetch_warnings,
        )

    return server


def serve(project_root: Path | None = None, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> None:
    server = AgentBServer(project_root or _project_root())
    reader = stdin or sys.stdin.buffer
    writer = stdout or sys.stdout.buffer
    for request in _read_messages(reader):
        response = server.handle_request(request)
        if response is not None:
            _write_message(writer, response)


def _run_payload(result: Any, *, sources: list[str], skipped_sources: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "sources": sources,
        "skipped_sources": skipped_sources,
        "summary": result.summary,
        "job_count": len(result.rows),
        "output_artifact_id": result.output_artifact_id,
        "markdown_artifact_id": result.markdown_artifact_id,
        "review_workspace_index": result.summary.get("review_workspace_index"),
        "jobs": [_job_row_summary(row) for row in result.rows],
    }


def _job_row_summary(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "job_id",
        "source_id",
        "source_job_id",
        "title",
        "company",
        "location",
        "work_mode",
        "state",
        "score",
        "coverage",
        "review_reasons",
        "link",
        "canonical_job_url",
        "application_destination",
        "review_path",
        "agent_a_handoff",
        "description_hash",
        "snapshot_artifact_id",
        "description_status",
        "warnings",
        "unknown_fields",
    )
    return {key: row.get(key) for key in keys if key in row}


def _resolved_sources(
    project_root: Path,
    sources: list[str] | None,
    *,
    include_jobspy: bool,
) -> tuple[list[str], list[dict[str, str]]]:
    skipped: list[dict[str, str]] = []
    if _is_auto_sources(sources):
        resolved, skipped = _auto_enabled_sources(project_root)
    else:
        resolved = list(sources or [])
    if include_jobspy and "jobspy_mcp_candidate" not in resolved:
        resolved.append("jobspy_mcp_candidate")
    if not resolved:
        raise ValueError("no enabled Agent B discovery sources are configured")
    return resolved, skipped


def _sources(arguments: dict[str, Any]) -> list[str] | None:
    value = arguments.get("sources")
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError("sources must be a list of non-empty strings")
    return [item.strip() for item in value]


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing required string argument: {key}")
    return value.strip()


def _optional_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    stripped = value.strip()
    return stripped or None


def _string_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _validate_public_job_url(url: str | None, *, label: str) -> str:
    if not url:
        raise ValueError(f"{label} is required")
    stripped = url.strip()
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError(f"{label} must be an http(s) URL")
    binary_suffixes = (
        ".7z",
        ".doc",
        ".docx",
        ".dmg",
        ".exe",
        ".gz",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".tar",
        ".tgz",
        ".zip",
    )
    if parsed.path.lower().endswith(binary_suffixes):
        raise ValueError(f"{label} cannot target an obvious binary download")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(f"{label} cannot target localhost")
    try:
        address = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError(f"{label} cannot target a private or local network address")
    return stripped


def _fetched_text_handoff_reason(text: str) -> str | None:
    stripped = text.strip()
    if len(stripped) < MIN_FETCHED_JOB_TEXT_CHARS:
        return "fetched content is too short to be a usable job description"
    lowered = " ".join(stripped.lower().split())
    blocked_markers = (
        "enable javascript",
        "please enable javascript",
        "captcha",
        "access denied",
        "403 forbidden",
        "sign in to view",
        "login to view",
        "verify you are human",
        "temporarily blocked",
    )
    for marker in blocked_markers:
        if marker in lowered:
            return f"fetched page appears blocked or login-gated: {marker}"
    job_markers = (
        "responsibilities",
        "requirements",
        "qualifications",
        "about the job",
        "job description",
        "experience",
        "apply",
        "employment",
        "role",
    )
    if not any(marker in lowered for marker in job_markers):
        return "fetched content does not look like a job description"
    return None


def _fetch_import_needs_refresh(store: SpaceStore, result: dict[str, Any], normalized_text: str, url: str) -> bool:
    duplicate_signals = result.get("duplicate_signals") or []
    reused_existing = any(
        signal.get("risk") == "exact" and signal.get("matched_job_id") == result.get("job_id")
        for signal in duplicate_signals
    )
    if not reused_existing:
        return False
    if result.get("description_hash") != _sha256_text(normalized_text.strip()):
        return True
    from app.discovery.manual_import import extract_job_description
    from app.storage.space import stable_json

    with store.connect() as db:
        row = db.execute(
            "SELECT extraction_json FROM job_extractions WHERE job_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (result.get("job_id"),),
        ).fetchone()
    if row is None:
        return True
    current = row["extraction_json"]
    refreshed = stable_json(extract_job_description(normalized_text.strip(), canonical_url=url))
    return current != refreshed


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_fetched_job_text(fetched_text: str, url: str) -> tuple[str, list[str]]:
    text = fetched_text.strip()
    warnings: list[str] = []
    if _fetch_simplification_failed(text):
        return text, ["fetch_simplification_failed_retry_raw"]
    jobposting = _extract_jobposting_jsonld(text)
    if jobposting:
        normalized = _jobposting_to_import_text(jobposting, url)
        if normalized:
            warnings.append("normalized_from_json_ld_jobposting")
            return normalized, warnings
    meta_text = _meta_jobposting_to_import_text(text, url)
    if meta_text:
        warnings.append("normalized_from_html_meta")
        return meta_text, warnings
    if _looks_like_html_document(text):
        warnings.append("raw_html_without_jobposting_metadata")
    return html_lib.unescape(text), warnings


def _fetch_simplification_failed(text: str) -> bool:
    return "<error>Page failed to be simplified from HTML</error>" in text


def _looks_like_html_document(text: str) -> bool:
    head = text[:500].lower()
    return "<!doctype html" in head or "<html" in head


def _extract_jobposting_jsonld(text: str) -> dict[str, Any] | None:
    scripts = re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        text,
        flags=re.I | re.S,
    )
    for script in scripts:
        payload = html_lib.unescape(script).strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        found = _find_jobposting_object(data)
        if found:
            return found
    return None


def _find_jobposting_object(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        raw_type = data.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(str(item).lower() == "jobposting" for item in types if item is not None):
            return data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                found = _find_jobposting_object(item)
                if found:
                    return found
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = _find_jobposting_object(value)
                if found:
                    return found
    if isinstance(data, list):
        for item in data:
            found = _find_jobposting_object(item)
            if found:
                return found
    return None


def _jobposting_to_import_text(job: dict[str, Any], url: str) -> str | None:
    title = _clean_scalar(job.get("title") or _nested_value(job.get("identifier"), "name"))
    company = _clean_scalar(_nested_value(job.get("hiringOrganization"), "name"))
    requisition = _clean_scalar(_nested_value(job.get("identifier"), "value"))
    location = _jobposting_location(job.get("jobLocation"))
    employment_type = _employment_type_label(_clean_scalar(job.get("employmentType")))
    posted = _clean_scalar(job.get("datePosted"))
    description = _clean_description(job.get("description"))
    if not any((title, company, description)):
        return None
    lines: list[str] = []
    if title:
        lines.append(f"Title: {title}")
    if company:
        lines.append(f"Company: {company}")
    if requisition:
        lines.append(f"Job ID: {requisition}")
    if location:
        lines.append(f"Location: {location}")
    if employment_type:
        lines.append(f"Employment type: {employment_type}")
    if posted:
        lines.append(f"Posted: {posted}")
    lines.append(f"Apply: {url}")
    if description:
        lines.append("")
        lines.extend(_sectioned_description_lines(description))
    return "\n".join(lines).strip()


def _meta_jobposting_to_import_text(text: str, url: str) -> str | None:
    title = _html_meta_content(text, "title") or _html_meta_property_content(text, "og:title")
    description = _html_meta_content(text, "description") or _html_meta_property_content(text, "og:description")
    if not description:
        return None
    lines = []
    if title:
        lines.append(f"Title: {_clean_scalar(title)}")
    lines.append(f"Apply: {url}")
    lines.append("")
    lines.extend(_sectioned_description_lines(_clean_description(description)))
    return "\n".join(lines).strip()


def _html_meta_content(text: str, name: str) -> str | None:
    pattern = rf"<meta\b(?=[^>]*\bname=[\"']{re.escape(name)}[\"'])(?=[^>]*\bcontent=[\"'](.*?)[\"'])[^>]*>"
    match = re.search(pattern, text, flags=re.I | re.S)
    return html_lib.unescape(match.group(1)).strip() if match else None


def _html_meta_property_content(text: str, prop: str) -> str | None:
    pattern = rf"<meta\b(?=[^>]*\bproperty=[\"']{re.escape(prop)}[\"'])(?=[^>]*\bcontent=[\"'](.*?)[\"'])[^>]*>"
    match = re.search(pattern, text, flags=re.I | re.S)
    return html_lib.unescape(match.group(1)).strip() if match else None


def _nested_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _clean_scalar(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = html_lib.unescape(str(value))
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _clean_description(value: Any) -> str:
    cleaned = html_lib.unescape(str(value or ""))
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"</(?:p|div|li|ul|ol|h[1-6])>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s+", "\n", cleaned)
    return cleaned.strip()


def _jobposting_location(value: Any) -> str | None:
    if isinstance(value, list):
        locations = [_jobposting_location(item) for item in value]
        return "; ".join(item for item in locations if item) or None
    if not isinstance(value, dict):
        return _clean_scalar(value)
    address = value.get("address")
    if isinstance(address, dict):
        parts = [
            _clean_scalar(address.get("addressLocality")),
            _clean_scalar(address.get("addressRegion")),
            _clean_scalar(address.get("addressCountry")),
        ]
        return ", ".join(part for part in parts if part) or None
    return _clean_scalar(value.get("name"))


def _employment_type_label(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.replace("_", " ").replace("-", " ").lower()
    if normalized == "full time":
        return "Full-time permanent"
    if normalized == "part time":
        return "Part-time"
    return value


def _sectioned_description_lines(description: str) -> list[str]:
    markers = [
        ("Responsibilities", r"What you(?:'|&#39;|’)?ll be doing:"),
        ("Requirements", r"What we need to see:"),
        ("Preferred qualifications", r"Ways to stand out(?: from the crowd)?:"),
    ]
    matches: list[tuple[int, int, str]] = []
    for heading, pattern in markers:
        match = re.search(pattern, description, flags=re.I)
        if match:
            matches.append((match.start(), match.end(), heading))
    if not matches:
        return ["Job description", description]
    matches.sort(key=lambda item: item[0])
    lines: list[str] = []
    intro = description[: matches[0][0]].strip()
    if intro:
        lines.extend(["About the job", intro, ""])
    for index, (start, end, heading) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(description)
        section = description[end:next_start].strip()
        lines.append(heading)
        for item in _description_items(section, heading):
            lines.append(f"- {item}")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _description_items(section: str, heading: str) -> list[str]:
    section = " ".join(section.split())
    if not section:
        return []
    starters = (
        "Develop",
        "Conduct",
        "Stay",
        "Responsible",
        "Collaborate",
        "BS or MS",
        "Bachelor",
        "Master",
        "5+",
        "3+",
        "2+",
        "1+",
        "Proven",
        "proven",
        "Understanding",
        "Proficiency",
        "Strong",
        "Familiar",
        "Experience",
        "Knowledge",
    )
    starter_pattern = "|".join(re.escape(starter) for starter in starters)
    chunks = re.split(rf"\s+(?=(?:{starter_pattern})\b)", section)
    items = [chunk.strip(" ;") for chunk in chunks if len(chunk.strip(" ;")) > 2]
    if len(items) <= 1:
        items = [item.strip() for item in re.split(r"(?<=[.!?])\s+", section) if item.strip()]
    return items[:20]


def _record_fetch_import_audit(store: SpaceStore, job_id: str, provenance: dict[str, Any]) -> None:
    from app.storage.space import new_id, stable_json, utc_now

    with store.connect() as db:
        db.execute(
            """
            INSERT INTO audit_events
              (id, actor, event_type, subject_type, subject_id, details_json, created_at)
            VALUES (?, 'agent_b_discovery', 'job_fetch_mcp_imported', 'job', ?, ?, ?)
            """,
            (
                new_id("audit"),
                job_id,
                stable_json(provenance),
                utc_now(),
            ),
        )


def _is_auto_sources(sources: list[str] | None) -> bool:
    return sources is None or sources == [] or [source.lower() for source in sources] == [AUTO_SOURCE_SENTINEL]


def _auto_enabled_sources(project_root: Path) -> tuple[list[str], list[dict[str, str]]]:
    config = _read_sources_config(project_root)
    selected: list[str] = []
    skipped: list[dict[str, str]] = []
    for source in config.get("sources", []):
        source_id = str(source.get("id") or "")
        status = str(source.get("status") or "")
        capabilities = set(source.get("capabilities") or [])
        if "discovery" not in capabilities:
            continue
        if status == "read_only_enabled":
            missing_secrets = [
                secret for secret in source.get("required_secrets", []) if not os.environ.get(str(secret))
            ]
            if missing_secrets:
                skipped.append(
                    {
                        "source_id": source_id,
                        "reason": f"missing required secret(s): {', '.join(missing_secrets)}",
                    }
                )
                continue
            selected.append(source_id)
            continue
        if status == "read_only_enabled_local":
            if _local_source_is_healthy(source):
                selected.append(source_id)
            else:
                skipped.append({"source_id": source_id, "reason": "local source is not healthy/running"})
    return selected, skipped


def _read_sources_config(project_root: Path) -> dict[str, Any]:
    for candidate in (project_root / "config" / "sources.json", project_root / "config" / "sources.example.json"):
        if candidate.exists():
            with candidate.open(encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError(f"{candidate} must contain a JSON object")
            return data
    raise ValueError("missing config/sources.json or config/sources.example.json")


def _local_source_is_healthy(source: dict[str, Any]) -> bool:
    endpoint = os.environ.get(str(source.get("local_endpoint_env") or "")) or str(
        source.get("default_local_endpoint") or ""
    )
    if not endpoint:
        return False
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return False
    health_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 80}/health"
    request = Request(health_url, headers={"User-Agent": "Job_Automation/0.1 local discovery"})
    try:
        with urlopen(request, timeout=1.0) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except (TimeoutError, URLError, OSError):
        return False


def _max_results(arguments: dict[str, Any]) -> int:
    value = arguments.get("max_results", 10)
    if not isinstance(value, int) or value < 1 or value > 25:
        raise ValueError("max_results must be an integer from 1 to 25")
    return value


def _limit(arguments: dict[str, Any]) -> int:
    value = arguments.get("limit", 25)
    if not isinstance(value, int) or value < 1 or value > 100:
        raise ValueError("limit must be an integer from 1 to 100")
    return value


def _review_path_for_saved_job(root: Path, job: dict[str, Any]) -> str | None:
    from app.discovery.job_review_workspace import short_job_id, slugify

    title = job.get("title") or "unknown-role"
    company = job.get("employer") or "unknown-company"
    path = root / slugify(company) / f"{slugify(title)}__{short_job_id(job['id'])}"
    if path.exists():
        return path.as_posix()
    return None


def _project_root() -> Path:
    return Path(os.environ.get("JOB_AUTOMATION_ROOT", Path.cwd())).resolve()


def _read_messages(stream: BinaryIO) -> Any:
    buffer = b""
    while True:
        chunk = stream.read(1)
        if not chunk:
            return
        buffer += chunk
        while True:
            parsed = _try_parse_framed_message(buffer)
            if parsed is not None:
                message, buffer = parsed
                yield message
                continue
            newline = buffer.find(b"\n")
            if newline >= 0 and not buffer.startswith(b"Content-Length:"):
                line = buffer[:newline].strip()
                buffer = buffer[newline + 1 :]
                if line:
                    yield json.loads(line.decode("utf-8"))
                continue
            break


def _try_parse_framed_message(buffer: bytes) -> tuple[dict[str, Any], bytes] | None:
    header_end = buffer.find(b"\r\n\r\n")
    separator_len = 4
    if header_end < 0:
        header_end = buffer.find(b"\n\n")
        separator_len = 2
    if header_end < 0:
        return None
    header = buffer[:header_end].decode("ascii", errors="replace")
    content_length: int | None = None
    for line in header.replace("\r\n", "\n").split("\n"):
        name, _, value = line.partition(":")
        if name.lower() == "content-length":
            content_length = int(value.strip())
            break
    if content_length is None:
        raise ValueError("MCP message missing Content-Length header")
    body_start = header_end + separator_len
    body_end = body_start + content_length
    if len(buffer) < body_end:
        return None
    body = buffer[body_start:body_end]
    return json.loads(body.decode("utf-8")), buffer[body_end:]


def _write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = (json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    stream.write(body)
    stream.flush()


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _log(message: str) -> None:
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "stdio":
        serve()
        return 0
    if FastMCP is not None:
        transport = argv[0] if argv else "stdio"
        build_fastmcp_server().run(transport=transport)
        return 0
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
