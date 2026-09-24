"""Minimal OpenAI Responses API client for approved local provider calls."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class OpenAIResponseError(RuntimeError):
    """Raised when the Responses API call fails or returns unusable output."""


@dataclass(frozen=True)
class OpenAIResponseResult:
    output: dict[str, Any]
    response_id: str | None
    model: str | None
    usage: dict[str, Any]


RESPONSES_URL = "https://api.openai.com/v1/responses"


def create_structured_response(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict[str, Any],
    api_key: str | None = None,
    timeout_seconds: float = 30.0,
    max_output_tokens: int = 1800,
) -> OpenAIResponseResult:
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise OpenAIResponseError("OPENAI_API_KEY is not configured")

    payload = {
        "model": model,
        "store": False,
        "max_output_tokens": max_output_tokens,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "agent_a_keyword_plan",
                "strict": True,
                "schema": json_schema,
            }
        },
    }
    request = urllib.request.Request(
        RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - approved OpenAI endpoint only.
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise OpenAIResponseError(f"OpenAI Responses API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenAIResponseError(f"OpenAI Responses API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise OpenAIResponseError("OpenAI Responses API request timed out") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OpenAIResponseError("OpenAI Responses API returned non-JSON data") from exc
    if data.get("status") not in (None, "completed"):
        raise OpenAIResponseError(f"OpenAI Responses API status was {data.get('status')}")
    text = _extract_output_text(data)
    try:
        output = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenAIResponseError("OpenAI response did not contain valid keyword-plan JSON") from exc
    if not isinstance(output, dict):
        raise OpenAIResponseError("OpenAI response JSON must be an object")
    return OpenAIResponseResult(
        output=output,
        response_id=data.get("id"),
        model=data.get("model"),
        usage=data.get("usage") or {},
    )


def _extract_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise OpenAIResponseError("OpenAI response did not include output text")
