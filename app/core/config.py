"""Validate Phase 01 synthetic configuration."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.contracts import CAPABILITY_FLAGS, ERROR_CODES


class ConfigError(ValueError):
    """Raised when a startup configuration contract is invalid."""


@dataclass(frozen=True)
class ValidationResult:
    config_dir: Path
    files_checked: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"missing required config file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return data


def _require_keys(data: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(keys - set(data))
    if missing:
        raise ConfigError(f"{label} missing required keys: {', '.join(missing)}")


def validate_config(config_dir: Path) -> ValidationResult:
    config_dir = config_dir.resolve()
    project_root = config_dir.parent
    models = _read_json(config_dir / "models.example.json")
    sources = _read_json(config_dir / "sources.example.json")
    policies = _read_json(config_dir / "policies.example.json")
    storage = _read_json(config_dir / "storage.example.json")

    _require_keys(models, {"schema_version", "provider", "agents"}, "models")
    _require_keys(models["provider"], {"name", "status", "personal_data_allowed"}, "models.provider")
    allowed_provider_statuses = {"deferred_for_privacy_review", "approved_for_keyword_planning"}
    if models["provider"]["status"] not in allowed_provider_statuses:
        raise ConfigError("models.provider.status must be deferred or approved only for keyword planning")
    if models["provider"]["status"] == "approved_for_keyword_planning":
        allowed_stages = set(models["provider"].get("allowed_stages", []))
        if allowed_stages != {"keyword_planning"}:
            raise ConfigError("approved provider use must be limited to keyword_planning")
    for agent_name, agent_config in models["agents"].items():
        _require_keys(agent_config, {"default_model", "fallback_models", "max_schema_repairs"}, agent_name)
        if agent_config["max_schema_repairs"] > 1:
            raise ConfigError(f"{agent_name} exceeds Phase 01 schema-repair limit")

    _require_keys(sources, {"schema_version", "sources"}, "sources")
    for source in sources["sources"]:
        _require_keys(source, {"id", "name", "capabilities", "status"}, "source")
        unknown_flags = set(source["capabilities"]) - set(CAPABILITY_FLAGS)
        if unknown_flags:
            raise ConfigError(f"{source['id']} has unknown capability flags: {sorted(unknown_flags)}")
        if source["status"] == "enabled_live":
            raise ConfigError(f"{source['id']} cannot be live-enabled in Phase 01")

    _require_keys(policies, {"schema_version", "mode", "submission", "error_codes"}, "policies")
    if policies["mode"] != "synthetic_dry_run":
        raise ConfigError("policies.mode must be synthetic_dry_run in Phase 01")
    if policies["submission"]["live_submission_enabled"] is not False:
        raise ConfigError("live submission must be disabled")
    unknown_errors = set(policies["error_codes"]) - set(ERROR_CODES)
    if unknown_errors:
        raise ConfigError(f"unknown configured error codes: {sorted(unknown_errors)}")

    _require_keys(storage, {"schema_version", "private_root", "secret_store", "git_exclusions"}, "storage")
    if storage["private_root"] != "private":
        raise ConfigError("Phase 01 private_root must be the local private directory")
    if not storage["secret_store"]["configured"]:
        # This is acceptable in Phase 01 because real secrets are not used.
        pass

    from app.core.agents import validate_agent_packages
    from app.mcp.runtime import ToolRegistry, validate_phase04_tool_coverage

    agent_packages = validate_agent_packages(project_root, config_dir)
    validate_phase04_tool_coverage(agent_packages, ToolRegistry())
    agent_files = tuple(
        path.relative_to(project_root).as_posix()
        for package in agent_packages
        for path in (
            package.instruction_path,
            package.contributor_path,
            package.config_path,
            package.mcp_path,
            *package.skill_paths,
        )
    )

    return ValidationResult(
        config_dir=config_dir,
        files_checked=(
            "models.example.json",
            "sources.example.json",
            "policies.example.json",
            "storage.example.json",
            *agent_files,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 01 configuration contracts.")
    parser.add_argument("--config-dir", default="config", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_config(args.config_dir)
    except ConfigError as exc:
        print(f"configuration invalid: {exc}", file=sys.stderr)
        return 1
    print(
        "configuration valid: "
        f"{result.config_dir} ({', '.join(result.files_checked)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
