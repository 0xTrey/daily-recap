"""
LLM client with three-tier fallback: local -> nvidia -> strategic.

Uses LLMGateway from ~/Projects/llm-gateway/.
"""

import json
import logging
import re

from llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

FALLBACK_ORDER = ["local", "nvidia", "strategic"]


def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Call LLM with three-tier fallback. Returns raw text response."""
    last_error = None

    for profile in FALLBACK_ORDER:
        try:
            logger.info(f"Trying LLM profile: {profile}")
            gateway = LLMGateway(profile=profile)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            result = gateway.chat(messages, temperature=temperature, max_tokens=max_tokens)
            if result:
                logger.info(f"LLM call succeeded on profile: {profile}")
                return result
        except Exception as e:
            last_error = e
            logger.warning(f"LLM profile {profile} failed: {e}")
            continue

    raise RuntimeError(f"All LLM profiles failed. Last error: {last_error}")


def _strip_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def call_llm_json(system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 4096) -> list[dict]:
    """Call LLM expecting a JSON array response. Retries once on parse failure."""
    raw = call_llm(system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens)
    cleaned = _strip_fences(raw)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return []
    except json.JSONDecodeError:
        pass

    # Retry with stricter prompt
    logger.warning("JSON parse failed, retrying with stricter prompt")
    strict_suffix = (
        "\n\nCRITICAL: Your response must be ONLY a valid JSON array. "
        "No markdown, no explanation, no code fences. Start with [ and end with ]."
    )
    raw = call_llm(system_prompt, user_prompt + strict_suffix, temperature=0.0, max_tokens=max_tokens)
    cleaned = _strip_fences(raw)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed on retry: {e}")
        logger.error(f"Raw output: {raw[:500]}")

    return []
