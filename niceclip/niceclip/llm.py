"""Optional Claude-powered re-ranking of candidate clips.

Entirely optional: if the `anthropic` SDK is missing or no credentials are
configured, `rank_with_claude` returns None and the heuristic ranking stands.
Credentials resolve from the environment (ANTHROPIC_API_KEY etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from .analyzer import Candidate

log = logging.getLogger("niceclip.llm")

DEFAULT_MODEL = "claude-opus-5"

_SYSTEM = (
    "You are a short-form video editor who has grown multiple accounts past a "
    "million followers. You are given candidate segments from a longer video, "
    "each with a transcript excerpt and a heuristic score. Pick the segments "
    "most likely to perform as standalone TikTok/Reels/Shorts clips: strong "
    "hook in the first seconds, self-contained payoff, emotional or "
    "informational punch. Prefer variety over near-duplicates. For each pick, "
    "write a punchy title (max 60 chars, no hashtags, no quotes around it) "
    "and one short sentence on why it will hold attention."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "title", "score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def claude_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    import os

    return bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


def rank_with_claude(
    candidates: list[Candidate],
    max_clips: int,
    model: str = DEFAULT_MODEL,
) -> Optional[list[Candidate]]:
    """Ask Claude to choose and title the best clips.

    Returns a re-ranked candidate list, or None on any failure so the caller
    falls back to heuristic ranking.
    """
    try:
        import anthropic
    except ImportError:
        return None

    speakable = [c for c in candidates if c.text.strip()]
    if not speakable:
        return None
    pool = speakable[: min(len(speakable), 25)]

    lines = []
    for i, c in enumerate(pool):
        excerpt = c.text if len(c.text) <= 700 else c.text[:700] + "…"
        lines.append(
            f"[{i}] {c.start:.0f}s–{c.end:.0f}s (heuristic {c.score:.0f}/100): {excerpt}"
        )
    user_msg = (
        f"Candidate segments:\n\n" + "\n\n".join(lines) +
        f"\n\nSelect the best {max_clips} segments (fewer only if the pool is "
        f"genuinely weak), ranked best first. Score each 0-100 for expected "
        f"short-form performance."
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        if response.stop_reason == "refusal":
            log.warning("Claude declined the ranking request")
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
    except anthropic.AuthenticationError:
        log.warning("Anthropic credentials invalid — skipping AI ranking")
        return None
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit — skipping AI ranking")
        return None
    except anthropic.APIStatusError as e:
        log.warning("Anthropic API error %s — skipping AI ranking", e.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Cannot reach Anthropic API — skipping AI ranking")
        return None
    except (json.JSONDecodeError, StopIteration, KeyError, TypeError) as e:
        log.warning("Unexpected AI ranking response (%s) — skipping", e)
        return None

    ranked: list[Candidate] = []
    for item in data.get("clips", []):
        idx = item.get("id")
        if not isinstance(idx, int) or not (0 <= idx < len(pool)):
            continue
        c = pool[idx]
        c.title = str(item.get("title", ""))[:80]
        c.reason = str(item.get("reason", c.reason))
        c.score = float(max(0, min(100, item.get("score", c.score))))
        ranked.append(c)
    return ranked or None
