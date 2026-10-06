"""The account-brief generator against the real Anthropic SDK (Bedrock Mantle client),
with the HTTP layer replaced by a mock transport so the wire format is checked."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from anthropic import AnthropicBedrockMantle, BetaRefusalFallbackMiddleware, DefaultHttpxClient

from leadintel.ai.brief import (
    SYSTEM_PROMPT,
    TOOL_NAME,
    BriefGenerator,
    BriefInput,
    BriefUnavailableError,
)

BRIEF = {
    "summary": "Northwind Analytics is a 312-person revenue intelligence vendor in Austin.",
    "why_now": [
        "Raised a $40M Series B (funding signal, 9 days ago)",
        "Hiring SDRs",
        "New CMO",
        "a",
        "b",
        "c",
    ],
    "talking_points": ["Scaling the SDR team after the Series B"],
    "risks": ["Builds adjacent analytics in-house"],
    "recommended_next_step": "Email the Head of Revenue Operations referencing the benchmark"
    " report download.",
    "confidence": "medium",
}

INPUT = BriefInput(
    company={
        "name": "Northwind Analytics",
        "employee_count": 312,
        "industry": "Software Development",
    },
    person={
        "title": "Head of Revenue Operations",
        "full_name": "Jordan Lee",
        "email": "jordan@x.com",
    },
    signals=[
        {"id": "s1", "type": "funding", "title": "Northwind raises $40M Series B", "days_ago": 9}
    ],
    score={"tier": "A", "total": 81.2},
    icp_name="B2B software, mid-market",
)


def _message(content: list[dict[str, Any]], stop_reason: str = "tool_use") -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "anthropic.claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 900, "output_tokens": 250},
    }


def _tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": "toolu_01", "name": TOOL_NAME, "input": payload}


def _client(
    responses: list[dict[str, Any]], captured: list[dict[str, Any]]
) -> AnthropicBedrockMantle:
    queue = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": json.loads(request.content),
            }
        )
        return httpx2.Response(200, json=queue.pop(0))

    return AnthropicBedrockMantle(
        aws_region="us-east-1",
        aws_access_key="AKIAEXAMPLEKEY000000",
        aws_secret_key="test-secret",
        http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
        middleware=[BetaRefusalFallbackMiddleware([{"model": "anthropic.claude-opus-4-8"}])],
        max_retries=0,
    )


def test_generates_validated_brief_with_cached_prefix() -> None:
    captured: list[dict[str, Any]] = []
    generator = BriefGenerator(
        _client([_message([_tool_use(BRIEF)])], captured), model_id="anthropic.claude-opus-5-5"
    )
    brief = generator.generate(INPUT)

    assert brief.confidence == "medium"
    assert len(brief.why_now) == 5  # trimmed to the documented maximum
    (call,) = captured
    assert call["url"].startswith("https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages")
    assert call["headers"]["authorization"].startswith("AWS4-HMAC-SHA256")  # SigV4, no API key
    body = call["body"]
    assert body["model"] == "anthropic.claude-opus-5-5"
    assert body["system"] == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    assert body["tool_choice"] == {"type": "auto"}
    assert body["tools"][0]["name"] == TOOL_NAME
    assert body["output_config"] == {"effort": "medium"}
    assert "output_format" not in body
    assert "format" not in body["output_config"]  # no structured outputs on Bedrock
    user_text = body["messages"][0]["content"]
    # Data minimization: role goes to the model, identity and contact details do not.
    assert "Head of Revenue Operations" in user_text
    assert "Jordan" not in user_text
    assert "jordan@x.com" not in user_text
    assert "<account_data>" in user_text
    assert "<signals>" in user_text


def test_retries_once_when_the_tool_input_is_invalid() -> None:
    captured: list[dict[str, Any]] = []
    bad = _message([_tool_use({"summary": "missing fields"})])
    good = _message([_tool_use(BRIEF)])
    generator = BriefGenerator(_client([bad, good], captured), model_id="anthropic.claude-opus-5-5")
    assert generator.generate(INPUT).summary.startswith("Northwind")
    assert len(captured) == 2


def test_gives_up_without_a_tool_call() -> None:
    text_only = _message([{"type": "text", "text": "Here is a brief..."}], stop_reason="end_turn")
    generator = BriefGenerator(
        _client([text_only, text_only], []), model_id="anthropic.claude-opus-5-5"
    )
    with pytest.raises(BriefUnavailableError):
        generator.generate(INPUT)


def test_fingerprint_changes_with_input_and_ignores_contact_details() -> None:
    other_person = BriefInput(
        **{
            **INPUT.__dict__,
            "person": {"title": "Head of Revenue Operations", "full_name": "Someone Else"},
        }
    )
    assert INPUT.fingerprint() == other_person.fingerprint()
    newer = BriefInput(**{**INPUT.__dict__, "signals": [*INPUT.signals, {"id": "s2"}]})
    assert INPUT.fingerprint() != newer.fingerprint()
