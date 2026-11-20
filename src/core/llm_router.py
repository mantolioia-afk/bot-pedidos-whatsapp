"""Minimal client for a local Ollama server (no cloud, no API keys)."""
import os
from typing import Optional

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
REQUEST_TIMEOUT = 30.0


def check_ollama_status() -> dict:
    """Returns {'online': bool, 'modelos': [model names]}."""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        if resp.status_code == 200:
            modelos = [m.get("name", "") for m in resp.json().get("models", [])]
            return {"online": True, "modelos": modelos}
    except Exception:
        pass
    return {"online": False, "modelos": []}


def call_ollama(
    prompt: str,
    system_prompt: str = "",
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    timeout: float = REQUEST_TIMEOUT,
    formato_json: bool = True,
) -> Optional[str]:
    """One stateless call to Ollama. formato_json=False returns plain text.
    Returns None if Ollama is not running or the call fails."""
    status = check_ollama_status()
    if not status["online"] or not status["modelos"]:
        return None
    target_model = model or status["modelos"][0]
    payload = {
        "model": target_model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": int(max_tokens) if max_tokens and max_tokens > 0 else 1024,
        },
    }
    if formato_json:
        payload["format"] = "json"
    try:
        resp = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=timeout)
        if resp.status_code == 200:
            return resp.json().get("response")
    except Exception:
        return None
    return None
