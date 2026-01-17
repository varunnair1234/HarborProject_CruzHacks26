# backend/app/services/deepseek_client.py

import os
from typing import Any, Dict, List, Optional

import requests


class DeepSeekError(RuntimeError):
    """Raised when DeepSeek API call fails."""


def call_deepseek(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    timeout_s: int = 45,
    base_url: Optional[str] = None,
) -> str:
    """
    Call DeepSeek Chat Completions API and return assistant content (string).

    Env vars:
      - DEEPSEEK_API_KEY (required)
      - DEEPSEEK_MODEL (optional default model)
      - DEEPSEEK_BASE_URL (optional; defaults to DeepSeek chat completions endpoint)

    Args:
      messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
      model: model name (default from env or deepseek-reasoner)
      temperature: sampling temperature
      timeout_s: request timeout in seconds
      base_url: override URL (default from env or https://api.deepseek.com/v1/chat/completions)

    Returns:
      assistant message content (string)
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekError(
            "DEEPSEEK_API_KEY is not set. Add it as an environment variable."
        )

    url = (
        base_url
        or os.getenv("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com/v1/chat/completions"
    )
    model = model or os.getenv("DEEPSEEK_MODEL") or "deepseek-reasoner"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    try:
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout_s,
        )
    except requests.RequestException as e:
        raise DeepSeekError(f"Network error calling DeepSeek: {e}") from e

    # Raise with readable context on non-2xx
    if r.status_code < 200 or r.status_code >= 300:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise DeepSeekError(f"DeepSeek HTTP {r.status_code}: {detail}")

    try:
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        raise DeepSeekError(f"Unexpected DeepSeek response format: {r.text}") from e