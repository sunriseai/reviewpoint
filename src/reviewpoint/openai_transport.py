"""Optional OpenAI SDK transport, with bounded output and no raw-response logging."""

import os
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import InputError

DEFAULT_MODEL = "not-configured"


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    response_id: str
    model: str
    usage: dict[str, Any]


class Transport(Protocol):
    def complete(
        self, *, system: str, user: str, schema: dict[str, Any], model: str, max_output_tokens: int
    ) -> ProviderResponse: ...


class OpenAITransport:
    def complete(
        self, *, system: str, user: str, schema: dict[str, Any], model: str, max_output_tokens: int
    ) -> ProviderResponse:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise InputError(
                "OPENAI_API_KEY is required for live interpretation; never paste it into chat"
            )
        try:
            from openai import APIError, OpenAI
        except ImportError as exc:
            raise InputError("install the optional adapter with uv sync --extra openai") from exc
        try:
            with OpenAI(
                api_key=key, base_url="https://api.openai.com/v1", timeout=180, max_retries=0
            ) as client:
                response = client.responses.create(
                    model=model,
                    store=False,
                    max_output_tokens=max_output_tokens,
                    reasoning={"effort": "medium"},
                    input=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "reviewpoint_evaluation",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                )
        except APIError as exc:
            # SDK exceptions can include request/response content; never echo their text.
            status = getattr(exc, "status_code", None)
            raise InputError(
                f"OpenAI request failed ({type(exc).__name__}, status={status}); "
                "no recommendation was issued and no automatic retry was attempted"
            ) from None
        if response.status != "completed":
            raise InputError(
                f"OpenAI response is {response.status}; no partial interpretation accepted"
            )
        for item in response.output:
            if item.type == "message" and any(c.type == "refusal" for c in item.content):
                raise InputError("OpenAI refused the interpretation; no recommendation issued")
        if not response.output_text:
            raise InputError("OpenAI returned no structured interpretation")
        return ProviderResponse(
            text=response.output_text,
            response_id=response.id,
            model=response.model,
            usage=response.usage.model_dump() if response.usage else {},
        )
