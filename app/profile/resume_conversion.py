"""CLI for one-time-per-source-version private LaTeX resume conversion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.profile.resume_suggestions import convert_resume
from app.storage.space import SpacePaths, SpaceStore, SpaceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a private resume.tex to cached Markdown.")
    parser.add_argument("source", nargs="?", type=Path, default=Path("private/inputs/resume.tex"))
    parser.add_argument("--regenerate", action="store_true", help="Create a new cached conversion generation for this source hash.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    source = args.source if args.source.is_absolute() else root / args.source
    store = SpaceStore(SpacePaths.from_project_root(root))
    store.migrate()
    try:
        result = convert_resume(store, source, regenerate=args.regenerate)
    except SpaceError as exc:
        print(f"resume conversion failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "reused" if result.reused else "converted",
        "source_sha256": result.source_sha256,
        "conversion_sha256": result.conversion_sha256,
        "converter_version": result.converter_version,
        "markdown_path": result.markdown_path.relative_to(store.paths.private_root).as_posix(),
        "warnings": list(result.warnings),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
