"""Anthropic SDK wrapper.

One module-level `AsyncAnthropic` client (created lazily so missing API keys
don't crash app startup). Exposes a `stream_with_tools` async generator that
runs the tool-use loop: stream text deltas → see a tool_use → execute it →
loop back into Claude with the tool_result → stream the next assistant turn,
until Claude stops without calling a tool.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from anthropic import APIStatusError, AsyncAnthropic, BadRequestError

from .tools import TOOLS
from .tools import execute as execute_tool

log = logging.getLogger("homebase.chat")

# Per-tier models.
MODEL_LAYOUT_FAST = "claude-haiku-4-5-20251001"
MODEL_DEFAULT = "claude-sonnet-4-6"
MAX_TOKENS = 1024
MAX_TOOL_LOOPS = 4  # Defensive cap on the tool-use loop


_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    """Lazy singleton — only fails when actually needed, not on import."""
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = AsyncAnthropic(api_key=key)
    return _client


def pick_model(user_text: str) -> str:
    """Route simple layout commands to Haiku, everything else to Sonnet.

    The Sonnet model can also call the layout tools — Haiku is just the cheap
    path for messages we're confident are pure layout commands. Anything with
    a question word ('how', 'what', 'why', '?') is always Sonnet.
    """
    t = user_text.lower().strip()
    if "?" in t:
        return MODEL_DEFAULT
    if any(w in t for w in ("how", "what", "why", "summarize", "summary", "trend", "compare", "explain", "tell me")):
        return MODEL_DEFAULT
    layout_words = (
        "move",
        "hide",
        "show",
        "remove",
        "swap",
        "reorder",
        "top",
        "bottom",
        "first",
        "ticker",
        "reset",
        "put",
        "bring back",
    )
    if any(w in t for w in layout_words):
        return MODEL_LAYOUT_FAST
    return MODEL_DEFAULT


async def stream_with_tools(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    model: str,
) -> AsyncIterator[dict[str, Any]]:
    """Run the tool-use loop and yield server-sent events.

    Yielded event shapes:
      {"type": "text",       "delta": str}
      {"type": "tool_use",   "tool": str, "input": dict, "id": str}
      {"type": "tool_result","tool": str, "output": dict, "id": str}
      {"type": "model",      "name": str}            # which model is up
      {"type": "stop",       "reason": str}          # end of one model turn
      {"type": "done"}                               # end of overall response
      {"type": "error",      "message": str}

    `messages` is mutated in-place to capture assistant turns + tool results,
    so the caller can persist it to the session store.
    """
    client = get_client()

    yield {"type": "model", "name": model}

    for _ in range(MAX_TOOL_LOOPS):
        try:
            async with client.messages.stream(
                model=model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                # Stream text deltas as they arrive.
                async for text in stream.text_stream:
                    if text:
                        yield {"type": "text", "delta": text}

                final = await stream.get_final_message()

        except (BadRequestError, APIStatusError) as e:
            log.exception("Anthropic API error")
            yield {"type": "error", "message": f"Anthropic API: {getattr(e, 'message', str(e))}"}
            return
        except Exception as e:
            log.exception("Streaming failed")
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
            return

        # Persist the assistant turn (with its tool_use blocks if any).
        messages.append({"role": "assistant", "content": [_block_to_dict(b) for b in final.content]})

        yield {"type": "stop", "reason": final.stop_reason}

        if final.stop_reason != "tool_use":
            yield {"type": "done"}
            return

        # Execute each tool_use in order and feed results back as a single
        # user message with one tool_result block per tool_use, per Anthropic's
        # tool-use protocol.
        tool_results: list[dict[str, Any]] = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool_use", "tool": block.name, "input": block.input, "id": block.id}
            output = await execute_tool(block.name, block.input)
            yield {"type": "tool_result", "tool": block.name, "output": output, "id": block.id}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _stringify_tool_output(output),
                    "is_error": not output.get("ok", True),
                }
            )

        messages.append({"role": "user", "content": tool_results})
        # Loop and let Claude write the natural-language reply.

    yield {"type": "error", "message": "Tool loop exceeded — aborting to avoid runaway."}


def _block_to_dict(block) -> dict[str, Any]:
    """Normalize an SDK content block to the JSON shape Anthropic expects on input."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    # Defensive: return a best-effort dump
    return {"type": block.type}


def _stringify_tool_output(output: dict[str, Any]) -> str:
    """Anthropic accepts a string or a list of content blocks for tool_result
    content. A short JSON string is easiest for Claude to parse and cheapest
    on tokens.
    """
    import json

    return json.dumps(output, default=str)
