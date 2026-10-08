"""
ShopMate AI — Groq LLM Client (Phase 2, now built as part of Phase 3)

Groq exposes an OpenAI-compatible endpoint, so we use the official
`openai` Python package pointed at Groq's base URL instead of a
Groq-specific SDK — this is also what keeps the provider swappable
(switching to a different OpenAI-compatible host later is a base_url
+ model change, not a rewrite).

Structured output (JSON mode): we ask the model to return JSON via
`response_format={"type": "json_object"}`, which is the standard
OpenAI-compatible way to request machine-parseable output. This is
documented as one of the open decisions in the project's context
report — JSON mode was chosen over function-calling because it's the
simpler mechanism to get working first; if Groq's function-calling
support for this model proves more reliable in practice, this file is
the only place that needs to change.

Every call includes a strong system-prompt instruction describing the
exact JSON shape expected, since JSON mode guarantees valid JSON but
NOT that it matches a particular schema — that's why every caller of
`call_groq_json` still validates the result with a Pydantic model and
should be prepared to handle a validation error (see agent/graph.py's
retry-once behavior).
"""

import json
import os

from openai import AsyncOpenAI

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazily creates the Groq client so importing this module never fails
    just because GROQ_API_KEY isn't set yet (e.g. during Phase 0/1 testing)."""
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set in .env — get one at https://console.groq.com "
                "and add it before calling any agent/chat endpoint."
            )
        _client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    return _client


async def call_groq_json(system_prompt: str, user_prompt: str) -> dict:
    """
    Sends a chat completion request to Groq and returns the parsed JSON
    response body as a dict. Raises json.JSONDecodeError if the model
    somehow returns non-JSON despite json_object mode (rare, but
    callers should not assume this can never happen).
    """
    client = _get_client()
    model = os.getenv("GROQ_MODEL", DEFAULT_MODEL)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,  # low temperature — we want consistent structured output, not creativity
    )

    raw_content = response.choices[0].message.content
    return json.loads(raw_content)