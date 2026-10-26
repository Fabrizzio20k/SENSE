from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import requests


logger = logging.getLogger(__name__)


def log_payload(parameters: dict) -> None:
    payload = dict(parameters)
    messages = []
    for message in parameters["messages"]:
        content = message["content"]
        if isinstance(content, list):
            content = [{"type": item["type"], "text": item.get("text", "[imagen omitida]")}
                       for item in content]
        messages.append({"role": message["role"], "content": content})
    payload["messages"] = messages
    logger.warning("SENSE_LLM_REQUEST %s", json.dumps(payload, ensure_ascii=False))


def request_completion(url: str, model: str, prompt: str, image: Path | bytes | None = None,
                       *, max_tokens: int = 64, timeout: float = 180, temperature: float | None = None,
                       response_format: dict | None = None, system_prompt: str | None = None) -> dict:
    content = prompt
    if image is not None:
        raw = image.read_bytes() if isinstance(image, Path) else image
        mime = "image/png" if isinstance(image, Path) else "image/jpeg"
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}}]
    messages = [{"role": "user", "content": content}]
    if system_prompt is not None:
        messages.insert(0, {"role": "system", "content": system_prompt})
    parameters = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
    if temperature is not None:
        parameters["temperature"] = temperature
    if response_format is not None:
        parameters["response_format"] = response_format
    log_payload(parameters)
    try:
        response = requests.post(url, json=parameters, timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except Exception:
        logger.exception("SENSE_LLM_FAILURE")
        raise
    text = body["choices"][0]["message"]["content"]
    if not isinstance(text, str):
        raise ValueError("Gemma no devolvió texto.")
    logger.warning("SENSE_LLM_RESPONSE %s", json.dumps({"model": body.get("model", model), "content": text,
                                                           "usage": body.get("usage")}, ensure_ascii=False))
    return {"content": text.strip(), "usage": body.get("usage"), "model": body.get("model", model)}
