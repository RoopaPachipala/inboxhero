"""ROLL NUMBER: 1179353

Optional Gemini wrapper. Drafting works without this; I only call it to
smooth wording when a key is present. Rate-limit: sleep + one retry on 429.
"""

from __future__ import annotations

import time

import config


def polish(prompt: str) -> str | None:
    """Return model text, or None if we should stick to the template."""
    if not config.has_llm():
        return None
    try:
        from google import genai
    except ImportError:
        return None

    client = genai.Client(api_key=config.API_KEY)
    last_err = None
    for attempt in range(2):
        try:
            resp = client.models.generate_content(
                model=config.MODEL,
                contents=prompt,
            )
            text = (getattr(resp, "text", None) or "").strip()
            return text or None
        except Exception as exc:  # noqa: BLE001 - student code, log and fall back
            last_err = exc
            msg = str(exc).lower()
            if "429" in msg or "resource" in msg:
                time.sleep(4)
                continue
            break
    print(f"(llm skipped: {last_err})")
    return None
