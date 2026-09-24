from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from app.mcp.codex_agent_a_server import AgentAServer, _read_messages, _write_message
from app.mcp.runtime import ToolContext, build_phase04_registry
from app.storage.space import SpacePaths, SpaceStore


JOB_TEXT = """
Title: Python Backend Engineer
Requirements
- Python
- REST APIs
- Observability
"""


def _paths(temp_dir: str) -> SpacePaths:
    root = Path(temp_dir)
    return SpacePaths(
        private_root=root / "private",
        database=root / "private" / "db" / "space.sqlite3",
        artifacts=root / "private" / "artifacts",
    )


def _space(temp_dir: str) -> SpaceStore:
    paths = _paths(temp_dir)
    store = SpaceStore(paths)
    store.migrate()
    return store


class CodexAgentAMCPServerTests(unittest.TestCase):
    def test_framed_message_round_trip(self) -> None:
        output = io.BytesIO()
        _write_message(output, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
        messages = list(_read_messages(io.BytesIO(output.getvalue())))
        self.assertEqual(messages, [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}])

    def test_initialize_and_tool_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = AgentAServer(Path.cwd(), space_paths=_paths(temp_dir))
            initialized = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                }
            )
            listed = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "job-automation-agent-a")
        tool_names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertEqual(tool_names, {"agent_a_get_job", "agent_a_save_keyword_plan"})

    def test_agent_a_tools_fetch_job_and_save_keyword_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = _space(temp_dir)
            registry = build_phase04_registry(store, Path.cwd())
            saved = registry.call(
                ToolContext(agent_id="agent_b_discovery", task_id="task_b"),
                "jobs.save_job",
                {
                    "source_id": "manual_import",
                    "url": "https://example.test/job",
                    "description": JOB_TEXT,
                },
            )
            job_id = saved["result"]["job_id"]
            server = AgentAServer(Path.cwd(), space_paths=_paths(temp_dir))

            fetched = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "agent_a_get_job", "arguments": {"job_id": job_id}},
                }
            )
            planned = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "agent_a_save_keyword_plan",
                        "arguments": {
                            "job_id": job_id,
                            "keywords": [
                                {
                                    "term": "Python",
                                    "priority": "high",
                                    "mandate": "mandatory",
                                    "category": "skill",
                                    "rationale": "Python is listed as a requirement.",
                                }
                            ],
                            "model": {
                                "selected_model": "gpt-5.5",
                                "provider_mode": "codex_mcp",
                                "route_status": "codex_mcp_in_session",
                            },
                        },
                    },
                }
            )

        fetched_result = fetched["result"]["structuredContent"]
        planned_result = planned["result"]["structuredContent"]
        self.assertIn("Python Backend Engineer", fetched_result["description"])
        self.assertEqual(planned_result["model"]["provider_mode"], "codex_mcp")
        self.assertEqual(planned_result["model"]["route_status"], "codex_mcp_in_session")
        self.assertEqual(planned_result["priority_counts"], {"high": 1, "medium": 0, "low": 0})
        self.assertEqual(json.loads(planned["result"]["content"][0]["text"])["status"], "validated")


if __name__ == "__main__":
    unittest.main()
