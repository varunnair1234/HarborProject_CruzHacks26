import os
import time
from typing import Any, Dict, Optional

import requests


class GeminiClientError(RuntimeError):
    pass


def _env(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default)
    if val is None or val == "":
        raise GeminiClientError(f"Missing required env var: {name}")
    return val


def generate_text(prompt: str) -> str:
    """
    Minimal Gemini Flash wrapper.
    Returns model text only.

    Env:
      - GOOGLE_API_KEY (required)
      - GEMINI_MODEL (optional, default gemini-1.5-flash)
      - GEMINI_TIMEOUT_S (optional, default 20)
      - GEMINI_MAX_RETRIES (optional, default 2)
    """
    api_key = _env("GOOGLE_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    timeout_s = int(os.getenv("GEMINI_TIMEOUT_S", "20"))
    max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "2"))

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 512,
        },
    }

    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=timeout_s,
            )

            if resp.status_code != 200:
                last_err = f"{resp.status_code}: {resp.text}"
                raise GeminiClientError(last_err)

            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

        except (requests.RequestException, GeminiClientError) as e:
            last_err = str(e)
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise GeminiClientError(f"Gemini request failed {last_err}") from e
