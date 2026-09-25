from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.mcp.codex_agent_b_server import (
    AgentBServer,
    _auto_enabled_sources,
    _read_messages,
    _write_message,
)
from app.storage.space import SpacePaths


def _paths(temp_dir: str) -> SpacePaths:
    root = Path(temp_dir)
    return SpacePaths(
        private_root=root / "private",
        database=root / "private" / "db" / "space.sqlite3",
        artifacts=root / "private" / "artifacts",
    )


class CodexAgentBMCPServerTests(unittest.TestCase):
    def test_framed_message_round_trip(self) -> None:
        output = io.BytesIO()
        _write_message(output, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
        messages = list(_read_messages(io.BytesIO(output.getvalue())))
        self.assertEqual(messages, [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}])

    def test_initialize_and_tool_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = AgentBServer(Path.cwd(), space_paths=_paths(temp_dir))
            initialized = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                }
            )
            listed = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "job-automation-agent-b")
        tool_names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertEqual(
            tool_names,
            {
                "agent_b_fetch_jobs",
                "agent_b_preview_search",
                "agent_b_rebuild_review_workspace",
                "agent_b_get_review_index",
                "agent_b_list_saved_jobs",
                "agent_b_import_job_text",
            },
        )

    def test_preview_search_returns_query_plan_without_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = AgentBServer(Path.cwd(), space_paths=_paths(temp_dir))
            response = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "agent_b_preview_search",
                        "arguments": {
                            "sources": ["fixture_remote_jobs"],
                            "max_results": 2,
                        },
                    },
                }
            )

        result = response["result"]["structuredContent"]
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["sources"], ["fixture_remote_jobs"])
        self.assertEqual(result["job_count"], 0)
        self.assertEqual(result["summary"]["source_count"], 1)
        self.assertEqual(result["summary"]["query_plan"][0]["source_id"], "fixture_remote_jobs")

    def test_auto_sources_select_enabled_read_only_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            (root / "config" / "sources.example.json").write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "id": "fixture_remote_jobs",
                                "status": "synthetic_enabled",
                                "capabilities": ["discovery", "fixture"],
                            },
                            {
                                "id": "jobicy_api_candidate",
                                "status": "read_only_enabled",
                                "capabilities": ["discovery", "description_retrieval"],
                            },
                            {
                                "id": "jobspipe_candidate",
                                "status": "read_only_enabled",
                                "capabilities": ["discovery", "description_retrieval"],
                                "required_secrets": ["JOBSPIPE_API_KEY"],
                            },
                            {
                                "id": "jobspy_mcp_candidate",
                                "status": "read_only_enabled_local",
                                "capabilities": ["discovery", "description_retrieval"],
                                "default_local_endpoint": "http://127.0.0.1:9423/api",
                            },
                            {
                                "id": "linkedin",
                                "status": "manual_only_pending_permission",
                                "capabilities": ["import_only", "manual_handoff"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"JOBSPIPE_API_KEY": "test"}, clear=True):
                with patch("app.mcp.codex_agent_b_server._local_source_is_healthy", return_value=False):
                    selected, skipped = _auto_enabled_sources(root)

        self.assertEqual(selected, ["jobicy_api_candidate", "jobspipe_candidate"])
        self.assertEqual(skipped, [{"source_id": "jobspy_mcp_candidate", "reason": "local source is not healthy/running"}])

    def test_auto_sources_skip_missing_required_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            (root / "config" / "sources.example.json").write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "id": "jobicy_api_candidate",
                                "status": "read_only_enabled",
                                "capabilities": ["discovery"],
                            },
                            {
                                "id": "jobspipe_candidate",
                                "status": "read_only_enabled",
                                "capabilities": ["discovery"],
                                "required_secrets": ["JOBSPIPE_API_KEY"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                selected, skipped = _auto_enabled_sources(root)

        self.assertEqual(selected, ["jobicy_api_candidate"])
        self.assertEqual(
            skipped,
            [{"source_id": "jobspipe_candidate", "reason": "missing required secret(s): JOBSPIPE_API_KEY"}],
        )

    def test_preview_search_uses_auto_sources_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = AgentBServer(Path.cwd(), space_paths=_paths(temp_dir))
            with patch(
                "app.mcp.codex_agent_b_server._auto_enabled_sources",
                return_value=(["fixture_remote_jobs"], []),
            ):
                response = server.handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 8,
                        "method": "tools/call",
                        "params": {
                            "name": "agent_b_preview_search",
                            "arguments": {"max_results": 5},
                        },
                    }
                )

        result = response["result"]["structuredContent"]
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["sources"], ["fixture_remote_jobs"])
        self.assertEqual(result["summary"]["query_plan"][0]["max_results"], 5)

    def test_fetch_jobs_writes_review_workspace_and_lists_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = AgentBServer(Path.cwd(), space_paths=_paths(temp_dir))
            fetched = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "agent_b_fetch_jobs",
                        "arguments": {
                            "sources": ["fixture_remote_jobs", "fixture_india_jobs"],
                            "max_results": 2,
                        },
                    },
                }
            )
            listed = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "agent_b_list_saved_jobs", "arguments": {"limit": 10}},
                }
            )
            index = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {"name": "agent_b_get_review_index", "arguments": {}},
                }
            )
            fetched_result = fetched["result"]["structuredContent"]
            listed_result = listed["result"]["structuredContent"]
            index_result = index["result"]["structuredContent"]
            self.assertEqual(fetched_result["status"], "completed")
            self.assertGreaterEqual(fetched_result["job_count"], 1)
            self.assertTrue(Path(fetched_result["review_workspace_index"]).exists())
            self.assertIn("review_path", fetched_result["jobs"][0])
            self.assertNotIn("description", fetched_result["jobs"][0])
            self.assertGreaterEqual(listed_result["count"], 1)
            self.assertIn("snapshot_artifact_id", listed_result["jobs"][0])
            self.assertEqual(index_result["status"], "available")
            self.assertIn("Agent B Job Reviews", index_result["content"])

    def test_import_job_text_saves_matches_and_writes_review_workspace(self) -> None:
        description = """Title: LinkedIn Pasted Python Engineer
Company: Example Careers
Job ID: LINK-101
Location: Bengaluru
Work mode: Hybrid
Employment type: Full-time permanent
Experience: 1-3 years
Apply: https://careers.example.test/jobs/link-101

Responsibilities
- Build Python services for internal products

Requirements
- Python
- SQL
- REST APIs
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            server = AgentBServer(Path.cwd(), space_paths=_paths(temp_dir))
            imported = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {
                        "name": "agent_b_import_job_text",
                        "arguments": {
                            "url": "https://www.linkedin.com/jobs/view/link-101",
                            "description": description,
                        },
                    },
                }
            )
            result = imported["result"]["structuredContent"]
            self.assertEqual(result["status"], "imported")
            self.assertEqual(result["source_id"], "manual_import")
            self.assertEqual(result["title"], "LinkedIn Pasted Python Engineer")
            self.assertEqual(result["company"], "Example Careers")
            self.assertTrue(Path(result["review_workspace_index"]).exists())
            self.assertTrue(Path(result["review_path"]).exists())
            self.assertTrue((Path(result["review_path"]) / "job-description.txt").exists())
            self.assertIn(result["decision"], {"shortlisted", "needs_review", "rejected_by_preferences"})

    def test_rebuild_review_workspace_without_live_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            server = AgentBServer(Path.cwd(), space_paths=_paths(temp_dir))
            server.fetch_jobs(sources=["fixture_india_jobs"], max_results=1)
            rebuilt = server.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "agent_b_rebuild_review_workspace", "arguments": {}},
                }
            )
            result = rebuilt["result"]["structuredContent"]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["job_count"], 1)
            self.assertTrue(Path(result["index_path"]).exists())


if __name__ == "__main__":
    unittest.main()
