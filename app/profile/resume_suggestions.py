"""Private LaTeX resume conversion and Agent C suggestion artifact handling."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.storage.space import ArtifactRecord, SpaceError, SpaceStore, new_id, stable_json, utc_now

CONVERTER_VERSION = "simple-latex-markdown-v1"
SUGGESTION_VERSION = "agent-c-keyword-three-lines-v3"
MAX_RESUME_BYTES = 2_000_000
MAX_RESUME_CHARS = 100_000
MAX_SUGGESTION_BYTES = 256_000
CONTENT_TYPE = "application/vnd.job.resume-keyword-suggestions+json"


@dataclass(frozen=True)
class ResumeConversion:
    source_sha256: str
    conversion_sha256: str
    converter_version: str
    markdown_path: Path
    markdown: str
    reused: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuggestionResult:
    job_id: str
    suggestion_id: str
    artifact: ArtifactRecord
    review_path: Path
    payload: dict[str, Any]


def read_resume_source(store: SpaceStore) -> tuple[str, str, str]:
    """Read the one active private TeX resume after the MCP privacy gate."""
    source = store.paths.private_root / "inputs" / "resume.tex"
    if source.suffix.lower() != ".tex" or not source.is_file():
        raise SpaceError("no active resume.tex is set; call Agent C with a local .tex path")
    if source.stat().st_size > MAX_RESUME_BYTES:
        raise SpaceError("resume source exceeds the 2 MB processing limit")
    raw = source.read_bytes()
    if not raw:
        raise SpaceError("resume source is empty")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpaceError("resume .tex must be UTF-8 encoded") from exc
    if len(text) > MAX_RESUME_CHARS:
        raise SpaceError("resume source exceeds the text processing limit")
    return digest, source.name, text


def import_resume_source(store: SpaceStore, source_path: str | Path, *, force_regenerate: bool = False) -> tuple[str, str, str, bool]:
    """Replace the single active private resume from the path explicitly supplied by the user."""
    source = Path(source_path).expanduser().resolve()
    if source.suffix.lower() != ".tex" or not source.is_file():
        raise SpaceError("resume path must point to an existing .tex file")
    if source.stat().st_size > MAX_RESUME_BYTES:
        raise SpaceError("resume source exceeds the 2 MB processing limit")
    raw = source.read_bytes()
    if not raw:
        raise SpaceError("resume source is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpaceError("resume .tex must be UTF-8 encoded") from exc
    if len(text) > MAX_RESUME_CHARS:
        raise SpaceError("resume source exceeds the text processing limit")
    digest = hashlib.sha256(raw).hexdigest()
    private_dir = store.paths.private_root / "inputs"
    _secure_directory(private_dir)
    target = private_dir / "resume.tex"
    manifest_path = private_dir / "resume-manifest.json"
    manifest = _read_json_if_present(manifest_path)
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        markdown_path = private_dir / "resume.md"
        if not force_regenerate and markdown_path.is_file() and manifest.get("source_sha256") == digest:
            current_markdown_hash = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
            if current_markdown_hash == manifest.get("conversion_sha256"):
                return digest, source.name, "", True
        return digest, source.name, text, True
    if source != target.resolve():
        staging = private_dir / "resume.tex.pending"
        _write_private_bytes(staging, raw)
        os.replace(staging, target)
    else:
        target.chmod(0o600)
    markdown_path = private_dir / "resume.md"
    markdown_path.unlink(missing_ok=True)
    metadata = {
        "source_sha256": digest,
        "source_name": source.name,
        "conversion_sha256": None,
        "converter_version": None,
        "current_file": "resume.md",
        "generation": int(manifest.get("generation", 0)),
        "status": "conversion_required",
        "imported_at": utc_now(),
        "warnings": [],
    }
    _write_private_text(manifest_path, stable_json(metadata) + "\n")
    return digest, source.name, text, False


def save_model_conversion(
    store: SpaceStore,
    *,
    source_sha256: str,
    markdown: str,
    model: dict[str, Any] | None = None,
    prompt_version: str = "agent-c-resume-markdown-v1",
    converter_version: str = "codex-session-markdown-v1",
    warnings: tuple[str, ...] = (),
    regenerate: bool = False,
) -> ResumeConversion:
    """Persist a Codex-generated Markdown conversion for the current source version."""
    current_hash, source_name, _ = read_resume_source(store)
    if source_sha256 != current_hash:
        raise SpaceError("resume source changed during conversion; retrieve the current source and retry")
    if not isinstance(markdown, str) or not markdown.strip() or len(markdown) > MAX_RESUME_CHARS:
        raise SpaceError("converted Markdown is empty or exceeds the text limit")
    if not markdown.lstrip().startswith("#"):
        raise SpaceError("converted resume must use Markdown headings for its document structure")
    if re.search(r"\\(?:documentclass|begin|end|section|subsection|item)\b", markdown):
        raise SpaceError("converted resume still contains LaTeX structural commands")
    private_dir = store.paths.private_root / "inputs"
    _secure_directory(private_dir)
    manifest_path = private_dir / "resume-manifest.json"
    manifest = _read_json_if_present(manifest_path)
    markdown_path = private_dir / "resume.md"
    if manifest and manifest.get("source_sha256") != source_sha256:
        raise SpaceError("resume source changed during conversion; import the current source and retry")
    if manifest and markdown_path.is_file() and not regenerate:
        existing = markdown_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(existing.encode("utf-8")).hexdigest()
        if digest == manifest.get("conversion_sha256"):
            return ResumeConversion(source_sha256, digest, str(manifest.get("converter_version", "unknown")), markdown_path, existing, True, tuple(manifest.get("warnings", [])))
        raise SpaceError("cached resume Markdown is invalid; explicitly request regeneration")
    generation = int(manifest.get("generation", 0)) + 1 if manifest else 1
    _write_private_text(markdown_path, markdown.rstrip() + "\n")
    metadata = {
        "source_sha256": source_sha256,
        "source_name": source_name,
        "converter_version": converter_version,
        "conversion_sha256": hashlib.sha256(markdown_path.read_bytes()).hexdigest(),
        "current_file": markdown_path.name,
        "generation": generation,
        "created_at": utc_now(),
        "regenerated_explicitly": bool(regenerate),
        "status": "ready",
        "prompt_version": prompt_version,
        "model": {"provider_mode": "codex_mcp", **(model or {})},
        "warnings": list(warnings),
    }
    _write_private_text(manifest_path, stable_json(metadata) + "\n")
    return ResumeConversion(source_sha256, metadata["conversion_sha256"], metadata["converter_version"], markdown_path, markdown_path.read_text(encoding="utf-8"), False)


def convert_resume(store: SpaceStore, source_path: Path, *, regenerate: bool = False) -> ResumeConversion:
    """Run the local fallback converter for an explicitly selected private TeX source."""
    source_hash, _, tex, _ = import_resume_source(store, source_path)
    markdown = latex_to_markdown(tex)
    warnings = latex_conversion_warnings(tex)
    if not markdown.strip():
        raise SpaceError("resume conversion produced no readable text")
    if not markdown.lstrip().startswith("#"):
        markdown = "# Resume\n\n" + markdown
    result = save_model_conversion(
        store, source_sha256=source_hash, markdown=markdown, model={"provider_mode": "local_fallback"},
        prompt_version="deterministic-local-fallback", converter_version=CONVERTER_VERSION,
        warnings=warnings, regenerate=regenerate,
    )
    return result


def latex_to_markdown(tex: str) -> str:
    """Convert common resume LaTeX structure while keeping each project/bullet separate."""
    text = re.sub(r"(?<!\\)%[^\n]*", "", tex)
    text = re.sub(r"\\begin\{(?:document|resume|itemize|enumerate|description)\}\s*", "\n", text)
    text = re.sub(r"\\end\{(?:document|resume|itemize|enumerate|description)\}\s*", "\n", text)
    text = re.sub(r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{[^{}]*\}(?:\s*\[[^]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}", "", text)

    def heading(match: re.Match[str]) -> str:
        level = 2 if match.group(1) in {"section", "cvsection"} else 3
        return "\n" + "#" * level + " " + _strip_latex(match.group(2)) + "\n"

    text = re.sub(r"\\(section|cvsection|subsection|subsubsection)\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}", heading, text)
    text = re.sub(
        r"\\(?:resumeProjectHeading|projectHeading)\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}(?:\s*\{((?:[^{}]|\{[^{}]*\})*)\})?",
        lambda m: "\n### " + _strip_latex(m.group(1)) + (" | " + _strip_latex(m.group(2)) if m.group(2) else "") + "\n",
        text,
    )
    text = re.sub(r"\\resumeItem\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}", lambda m: "\n- " + _strip_latex(m.group(1)), text)
    text = re.sub(r"\\resumeItemList(?:Start|End)\b", "\n", text)
    text = re.sub(r"\\item(?:\s*\[[^]]*\])?\s*", "\n- ", text)
    text = re.sub(r"\\(?:href|url)\s*\{([^{}]*)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}", r"\2 (\1)", text)
    text = re.sub(r"\\url\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:textbf|textit|emph|underline|mbox|makebox)\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}", r"\1", text)
    text = re.sub(r"\\(?:hfill|smallskip|medskip|bigskip|vspace|hspace)\*?(?:\s*\{[^{}]*\})?", " ", text)
    text = text.replace("\\\\", "\n").replace("~", " ")
    text = re.sub(r"\\(?:and|quad|qquad)\b", " | ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?(?:\s*\{((?:[^{}]|\{[^{}]*\})*)\})?", lambda m: m.group(1) or "", text)
    text = re.sub(r"\\[{}%&_#$]", lambda m: m.group(0)[1], text)
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(lines).strip() + "\n"


def _strip_latex(value: str) -> str:
    value = re.sub(r"\\(?:textbf|textit|emph|underline)\*?\s*\{((?:[^{}]|\{[^{}]*\})*)\}", r"\1", value)
    value = re.sub(r"\\[a-zA-Z]+\*?", "", value)
    value = re.sub(r"\\([{}%&_#$])", r"\1", value)
    value = value.replace("$", "").replace("{", "").replace("}", "")
    return value.strip()


def latex_conversion_warnings(tex: str) -> tuple[str, ...]:
    handled = {
        "documentclass", "usepackage", "begin", "end", "section", "subsection", "subsubsection", "cvsection",
        "item", "href", "url", "textbf", "textit", "emph", "underline", "mbox", "makebox", "hfill",
        "smallskip", "medskip", "bigskip", "vspace", "hspace", "and", "quad", "qquad", "newcommand",
        "renewcommand", "providecommand", "setlength", "addtolength", "pagestyle", "thispagestyle", "centering",
        "noindent", "raggedright", "raggedleft", "bfseries", "itshape", "normalfont", "fontsize", "selectfont",
        "color", "textcolor", "today", "linebreak", "newline", "clearpage", "newpage", "resumeProjectHeading",
        "projectHeading", "resumeItem", "resumeSubheading", "resumeProject", "vspace", "href", "email", "phone",
        "resumeItemListStart", "resumeItemListEnd",
    }
    commands = set(re.findall(r"\\([a-zA-Z@]+)\*?", tex))
    unsupported = sorted(command for command in commands if command not in handled)
    if not unsupported:
        return ()
    return ("Review the Markdown conversion: unrecognized LaTeX commands were simplified: " + ", ".join(unsupported[:20]),)


def get_suggestion_context(store: SpaceStore, job_id: str) -> dict[str, Any]:
    """Return only the assigned job's saved keyword plan and the current cached resume."""
    with store.connect() as db:
        job = db.execute("SELECT id, description_hash, snapshot_artifact_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise SpaceError("unknown job id")
        plan_row = db.execute(
            "SELECT id, artifact_id, artifact_sha256, description_hash FROM job_keyword_plans WHERE job_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        if plan_row is None:
            raise SpaceError("job has no saved Agent A keyword plan")
        artifact_row = db.execute(
            "SELECT storage_path FROM artifacts WHERE id = ? AND sha256 = ? ORDER BY version DESC LIMIT 1",
            (plan_row["artifact_id"], plan_row["artifact_sha256"]),
        ).fetchone()
    if artifact_row is None:
        raise SpaceError("saved keyword-plan artifact is unavailable")
    stored_plan = json.loads(Path(artifact_row["storage_path"]).read_text(encoding="utf-8"))
    validation = stored_plan.get("validation", {})
    if validation.get("status") != "passed":
        raise SpaceError("job's Agent A keyword plan is not validated")
    plan = stored_plan.get("keyword_plan", {})
    if not plan:
        raise SpaceError("saved Agent A keyword-plan artifact has an invalid structure")
    conversion = _current_conversion(store)
    if plan_row["description_hash"] != job["description_hash"]:
        raise SpaceError("keyword plan is stale for the current job description")
    return {
        "job_id": job_id,
        "description_hash": job["description_hash"],
        "keyword_plan_id": plan_row["id"],
        "keyword_plan_artifact_id": plan_row["artifact_id"],
        "keyword_plan_sha256": plan_row["artifact_sha256"],
        "keywords": plan.get("keywords", []),
        "resume_source_sha256": conversion.source_sha256,
        "resume_conversion_sha256": conversion.conversion_sha256,
        "resume_converter_version": conversion.converter_version,
        "resume_markdown": conversion.markdown,
        "conversion_warnings": list(conversion.warnings),
    }


def _current_conversion(store: SpaceStore) -> ResumeConversion:
    private_dir = store.paths.private_root / "inputs"
    source_hash, _, _ = read_resume_source(store)
    manifest = _read_json_if_present(private_dir / "resume-manifest.json")
    markdown_path = private_dir / "resume.md"
    if not manifest or manifest.get("source_sha256") != source_hash:
        raise SpaceError("resume conversion required for the active source; use Agent C's gated source and save tools")
    if not markdown_path.is_file():
        raise SpaceError("resume conversion required for the active source; use Agent C's gated source and save tools")
    markdown_path.chmod(0o600)
    markdown = markdown_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    if digest != manifest.get("conversion_sha256"):
        raise SpaceError("active resume Markdown failed its hash check; regenerate it explicitly")
    return ResumeConversion(source_hash, digest, str(manifest.get("converter_version", "unknown")), markdown_path, markdown, True, tuple(manifest.get("warnings", [])))


def validate_suggestions(payload: dict[str, Any], resume_markdown: str, keyword_terms: list[str] | None = None) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    unknown_input_fields = set(payload) - {"keyword_suggestions"}
    if unknown_input_fields:
        findings.append({"code": "unknown_suggestion_input_fields", "severity": "blocking"})
    if len(stable_json(payload).encode("utf-8")) > MAX_SUGGESTION_BYTES:
        findings.append({"code": "suggestion_payload_too_large", "severity": "blocking"})
    suggestions = payload.get("keyword_suggestions")
    if not isinstance(suggestions, list):
        findings.append({"code": "keyword_suggestions_required", "severity": "blocking"})
        suggestions = []
    planned = {str(term).strip().casefold() for term in (keyword_terms or []) if str(term).strip()}
    seen: set[str] = set()
    for index, item in enumerate(suggestions):
        label = f"keyword_suggestion_{index + 1}"
        if not isinstance(item, dict):
            findings.append({"code": f"{label}_invalid", "severity": "blocking"})
            continue
        allowed = {"keyword", "suggestions"}
        if set(item) - allowed:
            findings.append({"code": f"{label}_unknown_fields", "severity": "blocking"})
        keyword = str(item.get("keyword", "")).strip()
        normalized = keyword.casefold()
        if normalized in seen:
            findings.append({"code": f"{label}_duplicate_keyword", "severity": "blocking"})
        seen.add(normalized)
        variants = item.get("suggestions")
        if not keyword or not isinstance(variants, list) or len(variants) != 3:
            findings.append({"code": f"{label}_requires_exactly_three_suggestions", "severity": "blocking"})
            continue
        signatures: set[str] = set()
        for variant_index, variant in enumerate(variants):
            variant_label = f"{label}_variant_{variant_index + 1}"
            if not isinstance(variant, dict):
                findings.append({"code": f"{variant_label}_invalid", "severity": "blocking"})
                continue
            if set(variant) - {"section_or_project", "resume_pointer", "proposed_line", "rationale"}:
                findings.append({"code": f"{variant_label}_unknown_fields", "severity": "blocking"})
            destination = str(variant.get("section_or_project", "")).strip()
            pointer = str(variant.get("resume_pointer", "")).strip()
            proposal = str(variant.get("proposed_line", "")).strip()
            rationale = str(variant.get("rationale", "")).strip()
            if not all((destination, pointer, proposal, rationale)):
                findings.append({"code": f"{variant_label}_missing_field", "severity": "blocking"})
                continue
            if pointer not in resume_markdown:
                findings.append({"code": f"{variant_label}_resume_pointer_not_found", "severity": "blocking"})
            block = _project_block(resume_markdown, destination)
            if block is not None and pointer not in block:
                findings.append({"code": f"{variant_label}_cross_project_pointer", "severity": "blocking"})
            if len(_rendered(proposal)) > len(_rendered(pointer)):
                findings.append({"code": f"{variant_label}_exceeds_pointer_length", "severity": "blocking"})
            if normalized not in _rendered(proposal).casefold():
                findings.append({"code": f"{variant_label}_keyword_missing_from_line", "severity": "blocking"})
            signature = _rendered(proposal).casefold()
            if signature in signatures:
                findings.append({"code": f"{label}_duplicate_variants", "severity": "blocking"})
            signatures.add(signature)
    if planned and seen != planned:
        for missing in sorted(planned - seen):
            findings.append({"code": "keyword_coverage_missing:" + missing, "severity": "blocking"})
        for extra in sorted(seen - planned):
            findings.append({"code": "keyword_coverage_unplanned:" + extra, "severity": "blocking"})
    status = "blocking_failure" if any(item["severity"] == "blocking" for item in findings) else "passed"
    return {"status": status, "findings": findings, "checked_at": utc_now()}


def save_suggestions(store: SpaceStore, *, job_id: str, payload: dict[str, Any], model: dict[str, Any] | None = None) -> SuggestionResult:
    context = get_suggestion_context(store, job_id)
    validation = validate_suggestions(payload, context["resume_markdown"], [item["term"] for item in context["keywords"]])
    if validation["status"] != "passed":
        raise SpaceError("suggestion validation failed: " + ", ".join(f["code"] for f in validation["findings"]))
    output = {
        "schema_version": "2026-09-28.agent-c-v3",
        "job_id": job_id,
        "description_hash": context["description_hash"],
        "keyword_plan_id": context["keyword_plan_id"],
        "keyword_plan_artifact_id": context["keyword_plan_artifact_id"],
        "keyword_plan_sha256": context["keyword_plan_sha256"],
        "resume_source_sha256": context["resume_source_sha256"],
        "resume_conversion_sha256": context["resume_conversion_sha256"],
        "resume_converter_version": context["resume_converter_version"],
        "prompt_version": SUGGESTION_VERSION,
        "model": {"provider_mode": "codex_mcp", **(model or {})},
        "validation": validation,
        "keyword_suggestions": payload["keyword_suggestions"],
        "created_at": utc_now(),
    }
    artifact = store.artifacts.put_bytes(
        stable_json(output).encode("utf-8"), filename="suggestions.json", content_type=CONTENT_TYPE,
        owner="agent_c_resume_suggestions", artifact_id=new_id("agentc_suggestions"),
    )
    _secure_directory(artifact.path.parent)
    artifact.path.chmod(0o600)
    store.record_artifact(artifact)
    suggestion_id = new_id("suggestions")
    with store.connect() as db:
        db.execute(
            "INSERT INTO agent_c_suggestions (id, job_id, artifact_id, artifact_sha256, description_hash, keyword_plan_sha256, resume_source_sha256, resume_conversion_sha256, validation_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (suggestion_id, job_id, artifact.artifact_id, artifact.sha256, context["description_hash"], context["keyword_plan_sha256"], context["resume_source_sha256"], context["resume_conversion_sha256"], stable_json(validation), artifact.created_at),
        )
        db.execute(
            "INSERT INTO audit_events (id, actor, event_type, subject_type, subject_id, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id("audit"), "agent_c_resume_suggestions", "resume_suggestions_created", "job", job_id, stable_json({"artifact_id": artifact.artifact_id, "artifact_sha256": artifact.sha256, "resume_source_sha256": context["resume_source_sha256"], "resume_conversion_sha256": context["resume_conversion_sha256"]}), artifact.created_at),
        )
    from app.discovery.job_review_workspace import load_job_review_record, job_review_dir, review_root
    record = load_job_review_record(store, job_id)
    job_dir = job_review_dir(review_root(store), record)
    _secure_directory(job_dir)
    review_path = job_dir / "resume-keyword-suggestions.md"
    _write_private_text(review_path, render_suggestions_markdown(output, suggestion_id, artifact))
    return SuggestionResult(job_id, suggestion_id, artifact, review_path, output)


def render_suggestions_markdown(payload: dict[str, Any], suggestion_id: str, artifact: ArtifactRecord) -> str:
    lines = ["# Resume keyword suggestions", "", f"- Job ID: `{payload['job_id']}`", f"- Suggestion ID: `{suggestion_id}`", f"- Artifact: `{artifact.artifact_id}`", f"- Artifact SHA256: `{artifact.sha256}`", f"- Resume source SHA256: `{payload['resume_source_sha256']}`", f"- Resume Markdown SHA256: `{payload['resume_conversion_sha256']}`", f"- Keyword plan SHA256: `{payload['keyword_plan_sha256']}`", "", "Each keyword has three draft lines anchored to a resume pointer. Verify every line before manually editing the TeX resume.", ""]
    for item in payload["keyword_suggestions"]:
        lines.extend([f"## Keyword: {item['keyword']}", ""])
        for index, suggestion in enumerate(item["suggestions"], 1):
            lines.extend([f"### Suggestion {index}: {suggestion['section_or_project']}", "", f"**Resume pointer:** {suggestion['resume_pointer']}", f"**Suggested line:** {suggestion['proposed_line']}", f"**Why it may fit:** {suggestion['rationale']}", ""])
    return "\n".join(lines).rstrip() + "\n"


def _project_block(markdown: str, project: str) -> str | None:
    lines = markdown.splitlines()
    normalized = project.casefold()
    starts = [i for i, line in enumerate(lines) if line.startswith("#") and line.lstrip("# ").strip().casefold() == normalized]
    if not starts:
        return None
    start = starts[0]
    heading_level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("#"):
            level = len(lines[index]) - len(lines[index].lstrip("#"))
            if level <= heading_level:
                end = index
                break
    return "\n".join(lines[start:end])


def _rendered(value: str) -> str:
    value = re.sub(r"\*\*(.*?)\*\*|\*(.*?)\*|`([^`]*)`", lambda m: next((g for g in m.groups() if g is not None), ""), value)
    value = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|#{1,6}\s+)", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _read_json_if_present(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError as exc:
        raise SpaceError("could not restrict permissions on private resume storage") from exc


def _write_private_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError as exc:
        raise SpaceError("could not restrict permissions on a private resume artifact") from exc


def _write_private_bytes(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    try:
        path.chmod(0o600)
    except OSError as exc:
        raise SpaceError("could not restrict permissions on the private resume source") from exc
