# modules/llm/client.py — unified multi-provider LLM client with auto-fallback
#
# Provider chain (tried in order, falls back on rate-limit / auth errors):
#   Groq (Llama 3.3 70B) -> Cerebras (Llama 3.1 70B) -> Gemini Flash -> Anthropic Claude
#
# Usage:
#   from modules.llm.client import call_llm, parse_json_response
#   raw  = call_llm(system_prompt, user_prompt, max_tokens=1024)
#   data = parse_json_response(raw)

from __future__ import annotations
import json
import re
import time
import config

log = config.get_logger(__name__)

# ── Provider registry ──────────────────────────────────────────────────────────
# Tried in order; first one with a non-empty key that succeeds wins.

def _providers():
    """Build provider list at call-time so config values are up to date."""
    return [
        {
            "id":       "groq",
            "key":      config.GROQ_API_KEY,
            "type":     "oai",
            "base_url": "https://api.groq.com/openai/v1",
            "model":    "llama-3.3-70b-versatile",
        },
        {
            "id":       "cerebras",
            "key":      config.CEREBRAS_API_KEY,
            "type":     "oai",
            "base_url": "https://api.cerebras.ai/v1",
            "model":    "llama3.1-8b",
        },
        {
            "id":       "gemini",
            "key":      config.GEMINI_API_KEY,
            "type":     "oai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "model":    "gemini-2.0-flash",
        },
        {
            "id":       "anthropic",
            "key":      config.ANTHROPIC_API_KEY,
            "type":     "anthropic",
            "base_url": None,
            "model":    "claude-haiku-4-5-20251001",
        },
    ]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(x in msg for x in ("429", "rate_limit", "rate limit", "resource_exhausted", "quota"))


def _should_skip(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(x in msg for x in (
        "429", "rate_limit", "rate limit", "resource_exhausted", "quota",
        "401", "invalid_api_key", "authentication", "unauthorized",
        "404", "not found", "no such model", "does not exist",
    ))


def _call_oai(base_url: str, api_key: str, model: str,
              system: str, user: str, max_tokens: int, temperature: float) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(api_key: str, model: str,
                    system: str, user: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


# ── Public API ─────────────────────────────────────────────────────────────────

def call_llm(system: str, user: str,
             max_tokens: int = 1024, temperature: float = 0.2,
             _retry: int = 1) -> str:
    """
    Call LLM providers in priority order until one returns a response.
    Skips providers whose key is empty or that return auth/404 errors.
    On rate-limit, waits 30 s and retries the whole chain once.
    Raises RuntimeError if every provider fails after the retry.
    """
    errors = []
    rate_limited = False
    for p in _providers():
        if not p["key"]:
            continue
        try:
            if p["type"] == "anthropic":
                text = _call_anthropic(p["key"], p["model"], system, user, max_tokens)
            else:
                text = _call_oai(p["base_url"], p["key"], p["model"],
                                 system, user, max_tokens, temperature)
            log.debug("LLM call succeeded via %s", p["id"])
            return text
        except Exception as e:
            if _is_rate_limit(e):
                rate_limited = True
            if _should_skip(e):
                log.warning("Provider %s skipped: %s", p["id"], str(e)[:120])
                errors.append(f"{p['id']}: {str(e)[:80]}")
            else:
                log.warning("Provider %s unexpected error: %s", p["id"], e)
                errors.append(f"{p['id']}: {str(e)[:80]}")

    if rate_limited and _retry > 0:
        log.info("All providers rate-limited — waiting 35 s then retrying...")
        time.sleep(35)
        return call_llm(system, user, max_tokens, temperature, _retry=_retry - 1)

    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")


def parse_json_response(raw: str) -> dict:
    """Strip markdown fences / think-blocks and parse JSON from an LLM response."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = re.sub(r"<think>[\s\S]*?</think>\s*", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\n\nRaw:\n{raw[:400]}")
