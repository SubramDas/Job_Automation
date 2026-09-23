"""Controlled resume ingestion for Phase 03.

This module preserves the original document as an immutable artifact and performs only
conservative local extraction. Model-assisted fact extraction can build on the proposed
facts, but it must not auto-confirm them.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.storage.space import ArtifactRecord, SpaceError, SpaceStore

MAX_RESUME_BYTES = 5 * 1024 * 1024

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True)
class ResumeIngestionResult:
    original: ArtifactRecord
    extracted_text: str
    extraction_status: str
    uncertainty_labels: tuple[str, ...]
    proposed_facts: tuple[dict[str, object], ...]


def ingest_resume(path: Path, store: SpaceStore, *, owner: str = "candidate") -> ResumeIngestionResult:
    if path.suffix.lower() not in CONTENT_TYPES:
        raise SpaceError("resume ingestion currently accepts only PDF and DOCX files")
    size = path.stat().st_size
    if size <= 0 or size > MAX_RESUME_BYTES:
        raise SpaceError("resume file is empty or exceeds the Phase 03 size limit")

    content_type = CONTENT_TYPES[path.suffix.lower()]
    artifact = store.artifacts.put_file(path, content_type=content_type, owner=owner)
    store.record_artifact(artifact)

    text, labels = _extract_text(path, content_type)
    proposed = _propose_profile_facts(text, artifact.artifact_id) if text else ()
    status = "extracted_with_uncertainty" if labels else "extracted"
    if not text.strip():
        status = "needs_editable_copy_or_approved_ocr"
        labels = (*labels, "no_readable_text")
    return ResumeIngestionResult(
        original=artifact,
        extracted_text=text,
        extraction_status=status,
        uncertainty_labels=tuple(dict.fromkeys(labels)),
        proposed_facts=proposed,
    )


def _extract_text(path: Path, content_type: str) -> tuple[str, tuple[str, ...]]:
    if content_type == CONTENT_TYPES[".docx"]:
        return _extract_docx_text(path)
    return _extract_pdf_text(path)


def _extract_docx_text(path: Path) -> tuple[str, tuple[str, ...]]:
    labels: list[str] = []
    try:
        with zipfile.ZipFile(path) as docx:
            xml = docx.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise SpaceError("DOCX resume could not be parsed safely") from exc
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts = [node.text for node in root.findall(".//w:t", namespace) if node.text]
    text = "\n".join(parts)
    if len(text.strip()) < 200:
        labels.append("low_text_volume")
    return text, tuple(labels)


def _extract_pdf_text(path: Path) -> tuple[str, tuple[str, ...]]:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise SpaceError("PDF resume has an invalid header")
    labels = ["pdf_text_extraction_limited"]
    decoded = data.decode("latin-1", errors="ignore")
    candidates = re.findall(r"\(([^()]{2,200})\)", decoded)
    text = "\n".join(_clean_pdf_fragment(fragment) for fragment in candidates)
    text = "\n".join(line for line in text.splitlines() if line.strip())
    if len(text.strip()) < 200:
        labels.append("possible_scanned_or_unreadable_pdf")
    return text, tuple(labels)


def _clean_pdf_fragment(fragment: str) -> str:
    return (
        fragment.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\n", " ")
        .replace(r"\r", " ")
        .strip()
    )


def _propose_profile_facts(text: str, source_ref: str) -> tuple[dict[str, object], ...]:
    proposals: list[dict[str, object]] = []
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    if email_match:
        proposals.append(
            {
                "field_key": "contact.email",
                "value_type": "email",
                "value": email_match.group(0),
                "source_ref": source_ref,
                "source_span": {"start": email_match.start(), "end": email_match.end()},
                "provenance": {"method": "local_regex", "confidence": "candidate_review_required"},
                "sensitivity": "private",
            }
        )
    phone_match = re.search(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)", text)
    if phone_match:
        proposals.append(
            {
                "field_key": "contact.phone",
                "value_type": "phone",
                "value": phone_match.group(0).strip(),
                "source_ref": source_ref,
                "source_span": {"start": phone_match.start(), "end": phone_match.end()},
                "provenance": {"method": "local_regex", "confidence": "candidate_review_required"},
                "sensitivity": "sensitive",
            }
        )
    return tuple(proposals)
