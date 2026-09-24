"""Codex stdio MCP server for Agent A keyword planning.

This wrapper exposes a tiny tool surface to Codex:

- ``agent_a_get_job`` reads an assigned job snapshot and description.
- ``agent_a_save_keyword_plan`` stores Codex-generated ranked keywords as a private artifact.

The server intentionally delegates policy and persistence to the existing in-process MCP
facade in ``app.mcp.runtime`` so Codex gets the same authorization and validation behavior
as the local tests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, BinaryIO

from app.core.env import load_env_file
from app.mcp.runtime import ToolContext, build_phase04_registry
from app.storage.space import SpacePaths, SpaceStore

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - exercised when SDK is absent locally.
    FastMCP = None  # type: ignore[assignment]

SERVER_NAME = "job-automation-agent-a"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


AGENT_A_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "agent_a_get_job",
        "description": "Read a saved job snapshot and description for Agent A keyword planning.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["job_id"],
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Saved job ID produced by Agent B, for example job_xxx.",
                }
            },
        },
    },
    {
        "name": "agent_a_save_keyword_plan",
        "description": "Persist Codex-generated ranked resume keywords for a saved job.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["job_id", "keywords"],
            "properties": {
                "job_id": {"type": "string"},
                "keywords": {
                    "type": "array",
                    "description": "Ranked keyword items generated from the job description only.",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "required": ["term", "priority", "mandate", "category", "rationale"],
                        "properties": {
                            "term": {"type": "string"},
                            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                            "mandate": {
                                "type": "string",
                                "enum": ["mandatory", "recommended", "optional"],
                            },
                            "category": {
                                "type": "string",
                                "enum": [
                                    "skill",
                                    "tool",
                                    "platform",
                                    "responsibility",
                                    "domain_term",
                                    "seniority_signal",
                                    "architecture",
                                ],
                            },
                            "rationale": {"type": "string"},
                            "exact_terms": {"type": "array", "items": {"type": "string"}},
                            "synonyms": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "warnings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "code": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
                "model": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Optional Codex/session metadata to store with the plan.",
                },
                "prompt_version": {"type": "string"},
            },
        },
    },
)


class AgentAServer:
    def __init__(self, project_root: Path, space_paths: SpacePaths | None = None) -> None:
        self.project_root = project_root
        load_env_file(project_root)
        self.store = SpaceStore(space_paths or SpacePaths.from_project_root(project_root))
        self.store.migrate()
        self.registry = build_phase04_registry(self.store, project_root)

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
                result = {"tools": list(AGENT_A_TOOLS)}
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
        if name == "agent_a_get_job":
            result = self._project_tool("jobs.get_job", {"job_id": _required_str(arguments, "job_id")})
        elif name == "agent_a_save_keyword_plan":
            job_id = _required_str(arguments, "job_id")
            result = self._project_tool(
                "jobs.save_keyword_plan",
                {
                    "job_id": job_id,
                    "keywords": arguments.get("keywords") or [],
                    "warnings": arguments.get("warnings"),
                    "model": arguments.get("model") or {"provider_mode": "codex_mcp"},
                    "prompt_version": arguments.get("prompt_version", "agent-a-keyword-plan-v1"),
                },
            )
        else:
            raise ValueError(f"unknown tool: {name}")
        return {
            "content": [{"type": "text", "text": json.dumps(result, indent=2, sort_keys=True)}],
            "structuredContent": result,
            "isError": False,
        }

    def _project_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        job_id = str(args.get("job_id", ""))
        response = self.registry.call(
            ToolContext(
                agent_id="agent_a_resume",
                task_id="codex_agent_a_mcp",
                assigned_job_ids=frozenset({job_id}) if job_id else frozenset(),
            ),
            tool_name,
            args,
        )
        if not response["ok"]:
            error = response["error"]
            raise ValueError(f"{error['code']}: {error['message']}")
        return response["result"]


def build_fastmcp_server(project_root: Path | None = None) -> Any:
    if FastMCP is None:
        raise RuntimeError("The official MCP SDK is not installed. Use .venv-mcp/bin/python or install mcp.")
    agent_server = AgentAServer(project_root or _project_root())
    server = FastMCP(
        SERVER_NAME,
        instructions=(
            "Agent A keyword planning tools. Read saved job descriptions and persist "
            "Codex-generated high/medium/low keyword plans. Do not edit resume files."
        ),
    )

    @server.tool(
        name="agent_a_get_job",
        description="Read a saved job snapshot and description for Agent A keyword planning.",
    )
    def agent_a_get_job(job_id: str) -> dict[str, Any]:
        return agent_server._project_tool("jobs.get_job", {"job_id": job_id})

    @server.tool(
        name="agent_a_save_keyword_plan",
        description="Persist Codex-generated ranked resume keywords for a saved job.",
    )
    def agent_a_save_keyword_plan(
        job_id: str,
        keywords: list[dict[str, Any]],
        warnings: list[dict[str, Any]] | None = None,
        model: dict[str, Any] | None = None,
        prompt_version: str = "agent-a-keyword-plan-v1",
    ) -> dict[str, Any]:
        return agent_server._project_tool(
            "jobs.save_keyword_plan",
            {
                "job_id": job_id,
                "keywords": keywords,
                "warnings": warnings,
                "model": model or {"provider_mode": "codex_mcp"},
                "prompt_version": prompt_version,
            },
        )

    return server


def serve(project_root: Path | None = None, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> None:
    server = AgentAServer(project_root or _project_root())
    reader = stdin or sys.stdin.buffer
    writer = stdout or sys.stdout.buffer
    for request in _read_messages(reader):
        response = server.handle_request(request)
        if response is not None:
            _write_message(writer, response)


def _project_root() -> Path:
    return Path(os.environ.get("JOB_AUTOMATION_ROOT", Path.cwd())).resolve()


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing required string argument: {key}")
    return value.strip()


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


def main() -> int:
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
