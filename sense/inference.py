from __future__ import annotations

import base64
from pathlib import Path

import requests


def request_completion(url: str, model: str, prompt: str, image: Path | bytes | None = None,
                       *, max_tokens: int = 64, timeout: float = 180, temperature: float | None = None,
                       response_format: dict | None = None, system_prompt: str | None = None) -> dict:
    content = [{"type": "text", "text": prompt}]
    if image is not None:
        raw = image.read_bytes() if isinstance(image, Path) else image
        mime = "image/png" if isinstance(image, Path) else "image/jpeg"
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}})
    messages = [{"role": "user", "content": content}]
    if system_prompt is not None:
        messages.insert(0, {"role": "system", "content": system_prompt})
    parameters = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
    if temperature is not None:
        parameters["temperature"] = temperature
    if response_format is not None:
        parameters["response_format"] = response_format
    response = requests.post(url, json=parameters, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    text = body["choices"][0]["message"]["content"]
    if not isinstance(text, str):
        raise ValueError("Gemma no devolvió texto.")
    return {"content": text.strip(), "usage": body.get("usage"), "model": body.get("model", model)}
