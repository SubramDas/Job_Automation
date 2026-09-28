"""Small CLI for user-confirmed reusable answers in Space."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.profile.onboarding import OnboardingService
from app.storage.space import SpacePaths, SpaceStore


def _json_arg(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _space(project_root: Path) -> tuple[SpaceStore, OnboardingService]:
    store = SpaceStore(SpacePaths.from_project_root(project_root))
    store.migrate()
    return store, OnboardingService(store)


def add_answer(args: argparse.Namespace) -> int:
    _, onboarding = _space(args.project_root)
    answer_id = onboarding.create_reusable_answer(
        semantic_key=args.key,
        original_question=args.question,
        typed_value=_json_arg(args.value),
        unit=args.unit,
        scope=_json_arg(args.scope),
        sensitivity=args.sensitivity,
        reuse_permission=args.reuse_permission,
        provenance={"source": "user_cli", "note": args.note},
        expires_at=args.expires_at,
        actor="user",
    )
    print(answer_id)
    return 0


def list_answers(args: argparse.Namespace) -> int:
    store, _ = _space(args.project_root)
    with store.connect() as db:
        rows = db.execute(
            """
            SELECT id, semantic_key, original_question, scope_json, sensitivity,
                   reuse_permission, confirmation_state, expires_at, created_at
            FROM reusable_answers
            ORDER BY semantic_key, created_at DESC
            """
        ).fetchall()
    for row in rows:
        print(
            "\t".join(
                [
                    row["id"],
                    row["semantic_key"],
                    row["confirmation_state"],
                    row["sensitivity"],
                    row["reuse_permission"],
                    row["scope_json"],
                    row["expires_at"] or "",
                    row["original_question"],
                ]
            )
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage user-confirmed Space reusable answers.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing private/db/space.sqlite3.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add a confirmed reusable answer.")
    add.add_argument("--key", required=True, help="Semantic key, for example contact.email.")
    add.add_argument("--question", required=True, help="Original form question or label.")
    add.add_argument("--value", required=True, help="JSON value or plain string.")
    add.add_argument("--scope", default="{}", help='JSON scope, for example {"country":"IN"}.')
    add.add_argument("--unit")
    add.add_argument("--sensitivity", choices=("public", "private", "sensitive"), default="private")
    add.add_argument("--reuse-permission", default="same_semantic_key_and_scope")
    add.add_argument("--expires-at")
    add.add_argument("--note", default="confirmed by user for future scoped reuse")
    add.set_defaults(func=add_answer)

    list_cmd = subparsers.add_parser("list", help="List reusable-answer metadata without values.")
    list_cmd.set_defaults(func=list_answers)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


def main_with_args(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
