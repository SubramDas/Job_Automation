from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.core.config import ConfigError, validate_config


def _copy_project_contracts(target: Path) -> Path:
    config_target = target / "config"
    agents_target = target / "agents"
    config_target.mkdir()
    shutil.copytree("agents", agents_target)
    for path in Path("config").glob("*.example.json"):
        shutil.copy(path, config_target / path.name)
    return config_target


class ConfigValidationTests(unittest.TestCase):
    def test_example_config_is_valid(self) -> None:
        result = validate_config(Path("config"))
        self.assertIn("models.example.json", result.files_checked)
        self.assertIn("agents/agent_a_resume/AGENT.md", result.files_checked)
        self.assertIn(
            "agents/agent_c_application/skills/submission-reconciliation/SKILL.md",
            result.files_checked,
        )

    def test_live_submission_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            config_target = _copy_project_contracts(target)

            policy_path = config_target / "policies.example.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["submission"]["live_submission_enabled"] = True
            policy_path.write_text(json.dumps(policy), encoding="utf-8")

            with self.assertRaises(ConfigError):
                validate_config(config_target)

    def test_unknown_source_capability_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            config_target = _copy_project_contracts(target)

            sources_path = config_target / "sources.example.json"
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
            sources["sources"][0]["capabilities"].append("silent_submit")
            sources_path.write_text(json.dumps(sources), encoding="utf-8")

            with self.assertRaises(ConfigError):
                validate_config(config_target)

    def test_agent_instruction_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            config_target = _copy_project_contracts(target)

            manifest_path = target / "agents" / "agent_a_resume" / "agent.yaml"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["canonical_instruction"] = "../agent_b_discovery/AGENT.md"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(ConfigError):
                validate_config(config_target)

    def test_agent_unapproved_tool_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            config_target = _copy_project_contracts(target)

            mcp_path = target / "agents" / "agent_a_resume" / "mcp.json"
            mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
            mcp["tools"].append(
                {
                    "name": "applications.request_submit",
                    "scope": "not allowed for resume agent",
                    "external_effect": "review_queue",
                }
            )
            mcp_path.write_text(json.dumps(mcp), encoding="utf-8")

            with self.assertRaises(ConfigError):
                validate_config(config_target)

    def test_agent_model_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            config_target = _copy_project_contracts(target)

            manifest_path = target / "agents" / "agent_b_discovery" / "agent.yaml"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["model"]["default"] = "gpt-5.4"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(ConfigError):
                validate_config(config_target)


if __name__ == "__main__":
    unittest.main()
