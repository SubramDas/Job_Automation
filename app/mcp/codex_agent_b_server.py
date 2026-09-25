"""Codex stdio MCP server for Agent B job discovery.

This wrapper exposes a compact tool surface to Codex:

- ``agent_b_fetch_jobs`` runs read-only discovery and writes review files.
- ``agent_b_preview_search`` shows the query plan without live source calls.
- ``agent_b_rebuild_review_workspace`` regenerates readable files from Space.
- ``agent_b_get_review_index`` reads the generated review index.
- ``agent_b_list_saved_jobs`` returns a lightweight saved-job list.
- ``agent_b_import_job_text`` imports pasted job details and a source/apply link.

The server delegates discovery, policy checks, storage, and matching to the existing
Agent B runner and project MCP facade.
"""

from __future__ import annotations

import json
import os
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
from app.storage.space import SpacePaths, SpaceStore

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - exercised when SDK is absent locally.
    FastMCP = None  # type: ignore[assignment]

SERVER_NAME = "job-automation-agent-b"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
AUTO_SOURCE_SENTINEL = "auto"


AGENT_B_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "agent_b_fetch_jobs",
        "description": (
            "Run Agent B read-only job discovery, save matched jobs locally, and return "
            "a concise summary with review workspace paths."
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
            "and mirror it into the private review workspace."
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
                  ORDER BY mr.created_at DESC
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
        return {
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
        description="Run read-only Agent B job discovery and save reviewable jobs locally.",
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
        description="Import pasted job text and a job/apply link, then save, extract, match, and mirror it locally.",
    )
    def agent_b_import_job_text(
        url: str,
        description: str,
        source_id: str = "manual_import",
    ) -> dict[str, Any]:
        return agent_server.import_job_text(url=url, description=description, source_id=source_id)

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
