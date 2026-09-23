"""Validate and load Phase 02 agent instruction packages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import ConfigError, _read_json, _require_keys

AGENT_IDS: tuple[str, ...] = (
    "agent_a_resume",
    "agent_b_discovery",
    "agent_c_application",
)

REQUIRED_SKILLS: dict[str, tuple[str, ...]] = {
    "agent_a_resume": ("resume-evidence", "resume-tailoring", "resume-export-review"),
    "agent_b_discovery": ("job-discovery", "job-extraction", "job-matching"),
    "agent_c_application": ("form-preparation", "answer-resolution", "submission-reconciliation"),
}

ALLOWED_TOOLS: dict[str, tuple[str, ...]] = {
    "agent_a_resume": (
        "space.get_career_evidence",
        "jobs.get_job",
        "documents.extract_resume",
        "documents.render_resume",
        "documents.extract_text",
        "documents.render_preview",
        "documents.get_artifact",
        "review.create_question",
        "review.get_question_status",
        "workflow.save_stage_result",
        "workflow.save_checkpoint",
        "workflow.get_assigned_task",
    ),
    "agent_b_discovery": (
        "space.get_search_profile",
        "jobs.search_sources",
        "jobs.fetch_description",
        "jobs.save_job",
        "jobs.get_job",
        "jobs.evaluate_match",
        "review.create_question",
        "review.get_question_status",
        "workflow.save_stage_result",
        "workflow.save_checkpoint",
        "workflow.get_assigned_task",
    ),
    "agent_c_application": (
        "space.get_application_facts",
        "space.resolve_answer",
        "jobs.get_job",
        "documents.get_artifact",
        "review.create_question",
        "review.get_question_status",
        "review.submit_package_for_review",
        "applications.inspect_form",
        "applications.fill_fields",
        "applications.attach_resume",
        "applications.read_back",
        "applications.request_submit",
        "applications.get_confirmation",
        "applications.reconcile_attempt",
        "workflow.save_stage_result",
        "workflow.save_checkpoint",
        "workflow.get_assigned_task",
    ),
}


@dataclass(frozen=True)
class AgentPackage:
    agent_id: str
    package_dir: Path
    instruction_path: Path
    contributor_path: Path
    config_path: Path
    mcp_path: Path
    skill_paths: tuple[Path, ...]
    file_hashes: dict[str, str]


def _stable_json_hash(data: Any) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path, root: Path) -> tuple[str, str]:
    return path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_package_path(root: Path, relative_path: str, label: str) -> Path:
    if relative_path.startswith("/") or "\\" in relative_path:
        raise ConfigError(f"{label} must be a relative POSIX path")
    resolved = (root / relative_path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigError(f"{label} escapes the agent package: {relative_path}") from exc
    return resolved


def _read_json_compatible_yaml(path: Path) -> dict[str, Any]:
    # Phase 02 avoids a runtime YAML dependency. Manifests use JSON-compatible YAML.
    return _read_json(path)


def _validate_skill_paths(agent_id: str, package_dir: Path, manifest: dict[str, Any]) -> tuple[Path, ...]:
    skills = manifest.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ConfigError(f"{agent_id} must declare skills")
    by_id: dict[str, Path] = {}
    for skill in skills:
        if not isinstance(skill, dict):
            raise ConfigError(f"{agent_id} skill entries must be objects")
        _require_keys(skill, {"id", "path"}, f"{agent_id} skill")
        skill_id = skill["id"]
        if not isinstance(skill_id, str):
            raise ConfigError(f"{agent_id} skill id must be a string")
        path = _resolve_package_path(package_dir, skill["path"], f"{agent_id}.{skill_id}.path")
        if path.name != "SKILL.md":
            raise ConfigError(f"{agent_id}.{skill_id} must point to SKILL.md")
        if not path.is_file():
            raise ConfigError(f"{agent_id}.{skill_id} missing skill file: {path}")
        by_id[skill_id] = path

    expected = set(REQUIRED_SKILLS[agent_id])
    if set(by_id) != expected:
        raise ConfigError(f"{agent_id} skills must be {sorted(expected)}, got {sorted(by_id)}")
    return tuple(by_id[skill] for skill in REQUIRED_SKILLS[agent_id])


def _validate_tools(agent_id: str, mcp: dict[str, Any]) -> None:
    _require_keys(mcp, {"schema_version", "agent_id", "mode", "tools"}, f"{agent_id} MCP")
    if mcp["agent_id"] != agent_id:
        raise ConfigError(f"{agent_id} MCP agent_id mismatch")
    if mcp["mode"] != "synthetic_dry_run":
        raise ConfigError(f"{agent_id} MCP mode must remain synthetic_dry_run")
    allowed = set(ALLOWED_TOOLS[agent_id])
    declared = set()
    for tool in mcp["tools"]:
        if not isinstance(tool, dict):
            raise ConfigError(f"{agent_id} MCP tools must be objects")
        _require_keys(tool, {"name", "external_effect", "scope"}, f"{agent_id} MCP tool")
        declared.add(tool["name"])
        if tool["name"] not in allowed:
            raise ConfigError(f"{agent_id} declares unapproved tool: {tool['name']}")
        if tool["external_effect"] not in ("none", "local_draft", "review_queue"):
            raise ConfigError(f"{agent_id}.{tool['name']} has an unsafe external_effect")
    if not declared:
        raise ConfigError(f"{agent_id} MCP manifest must declare tools")


def validate_agent_packages(root: Path, config_dir: Path) -> tuple[AgentPackage, ...]:
    root = root.resolve()
    config_dir = config_dir.resolve()
    models = _read_json(config_dir / "models.example.json")
    packages: list[AgentPackage] = []
    agents_root = root / "agents"
    for agent_id in AGENT_IDS:
        package_dir = agents_root / agent_id
        if not package_dir.is_dir():
            raise ConfigError(f"missing agent package: {package_dir}")

        manifest_path = package_dir / "agent.yaml"
        manifest = _read_json_compatible_yaml(manifest_path)
        _require_keys(
            manifest,
            {
                "schema_version",
                "agent_id",
                "canonical_instruction",
                "contributor_instruction",
                "model",
                "skills",
                "mcp_manifest",
                "instruction_precedence",
            },
            agent_id,
        )
        if manifest["agent_id"] != agent_id:
            raise ConfigError(f"{agent_id} manifest agent_id mismatch")
        if agent_id not in models["agents"]:
            raise ConfigError(f"{agent_id} missing from model configuration")
        model_config = models["agents"][agent_id]
        if manifest["model"]["default"] != model_config["default_model"]:
            raise ConfigError(f"{agent_id} default model conflicts with config/models.example.json")
        if manifest["model"]["fallbacks"] != model_config["fallback_models"]:
            raise ConfigError(f"{agent_id} fallback models conflict with config/models.example.json")

        instruction_path = _resolve_package_path(
            package_dir, manifest["canonical_instruction"], f"{agent_id}.canonical_instruction"
        )
        contributor_path = _resolve_package_path(
            package_dir, manifest["contributor_instruction"], f"{agent_id}.contributor_instruction"
        )
        mcp_path = _resolve_package_path(package_dir, manifest["mcp_manifest"], f"{agent_id}.mcp_manifest")
        for path in (instruction_path, contributor_path, mcp_path):
            if not path.is_file():
                raise ConfigError(f"{agent_id} missing required file: {path}")

        skill_paths = _validate_skill_paths(agent_id, package_dir, manifest)
        mcp = _read_json(mcp_path)
        _validate_tools(agent_id, mcp)

        hash_items = dict(
            _file_hash(path, root)
            for path in (instruction_path, contributor_path, manifest_path, mcp_path, *skill_paths)
        )
        hash_items["effective_manifest"] = _stable_json_hash(
            {
                "agent_id": agent_id,
                "instruction_precedence": manifest["instruction_precedence"],
                "tools": sorted(tool["name"] for tool in mcp["tools"]),
                "model": manifest["model"],
            }
        )
        packages.append(
            AgentPackage(
                agent_id=agent_id,
                package_dir=package_dir,
                instruction_path=instruction_path,
                contributor_path=contributor_path,
                config_path=manifest_path,
                mcp_path=mcp_path,
                skill_paths=skill_paths,
                file_hashes=hash_items,
            )
        )
    return tuple(packages)
