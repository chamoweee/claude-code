"""Optional plain-English summary via the Claude API. Only runs when
ANTHROPIC_API_KEY is set; the model is given the already-computed tables and
insights and instructed to cite only those figures. If no key is present
this section is skipped entirely and the skip is logged -- no summary is
fabricated locally.
"""
from __future__ import annotations

import json

from .logutil import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "You are summarising a crypto market report for an Australian investor who prefers "
    "steadier, lower-risk exposure. You will be given JSON data: market overview, movers "
    "tables, insights, and portfolio actions -- all already computed. Write a short "
    "(150-250 word) plain-English summary of what matters today. "
    "STRICT RULE: only reference figures, coins, and facts present in the JSON you are given. "
    "Do not invent numbers, do not speculate beyond the data, and do not give financial advice -- "
    "describe what the data shows. If the JSON is sparse, say so briefly rather than filling gaps."
)


def generate_summary(report_data: dict, api_key: str | None, model: str = "claude-sonnet-5") -> str | None:
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set -- skipping plain-English summary")
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed -- skipping plain-English summary")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(report_data, default=str)}],
        )
        text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        return "\n".join(text_parts).strip() or None
    except Exception as exc:  # noqa: BLE001 - any API failure should degrade gracefully
        logger.warning("Claude summary generation failed: %s", exc)
        return None
