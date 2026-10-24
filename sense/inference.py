from __future__ import annotations

import base64
from pathlib import Path

import requests


def request_completion(url: str, model: str, prompt: str, image: Path | bytes | None = None,
                       *, max_tokens: int = 64, timeout: float = 180, temperature: float | None = None) -> dict:
    content = [{"type": "text", "text": prompt}]
    if image is not None:
        raw = image.read_bytes() if isinstance(image, Path) else image
        mime = "image/png" if isinstance(image, Path) else "image/jpeg"
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}})
    parameters = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}
    if temperature is not None:
        parameters["temperature"] = temperature
    response = requests.post(url, json=parameters, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    text = body["choices"][0]["message"]["content"]
    if not isinstance(text, str):
        raise ValueError("Gemma no devolvió texto.")
    return {"content": text.strip(), "usage": body.get("usage"), "model": body.get("model", model)}
