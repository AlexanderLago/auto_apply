# modules/llm/__init__.py
"""
LLM Module — Multi-Provider LLM Client with Auto-Fallback

This module provides a unified interface for calling multiple LLM providers.

## Provider Chain

Providers are tried in order. First successful response wins.

```
Groq (Llama 3.3 70B)
  ↓ (rate limit / error)
Cerebras (Llama 3.1 70B)
  ↓ (rate limit / error)
Gemini Flash
  ↓ (rate limit / error)
Anthropic Claude (Haiku/Sonnet)
```

## Components

### client.py — Unified LLM Client

**Functions:**
- `call_llm(system_prompt, user_prompt, **kwargs)` — Call LLM with auto-fallback
- `parse_json_response(response)` — Extract JSON from LLM response

**Usage:**
```python
from modules.llm.client import call_llm, parse_json_response

# Simple text response
response = call_llm(
    system_prompt="You are a helpful assistant.",
    user_prompt="What is 2+2?",
    max_tokens=100,
    temperature=0.7,
)

# JSON response
response = call_llm(
    system_prompt="Extract skills from JD as JSON.",
    user_prompt=jd_text,
    max_tokens=1024,
)
data = parse_json_response(response)
```

## Configuration

API keys in `.env`:
```bash
GROQ_API_KEY=...
CEREBRAS_API_KEY=...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
```

## Models

| Provider | Model | Speed | Quality | Cost |
|----------|-------|-------|---------|------|
| Groq | Llama 3.3 70B | ⚡⚡⚡ | ★★★★ | $ |
| Cerebras | Llama 3.1 70B | ⚡⚡⚡ | ★★★★ | $ |
| Gemini | Gemini 2.0 Flash | ⚡⚡⚡ | ★★★ | $ |
| Anthropic | Claude Haiku 4.5 | ⚡⚡ | ★★★★★ | $$ |

## Error Handling

- Rate limit (429): Try next provider
- Auth error (401): Skip provider, log warning
- Not found (404): Skip provider
- Network error: Retry 3 times, then next provider

## Performance

- Groq/Cerebras: ~1-3 seconds for 1000 tokens
- Gemini: ~2-5 seconds
- Anthropic: ~3-10 seconds (higher quality)
"""

from modules.llm.client import call_llm, parse_json_response

__all__ = ["call_llm", "parse_json_response"]
