from __future__ import annotations

import base64
import io
import json
from typing import Any

import requests
from PIL import Image


def encode_pil_to_base64(image: Image.Image, fmt: str = "JPEG") -> str:
    buffer = io.BytesIO()
    if fmt.upper() in ("JPEG", "JPG"):
        image.save(buffer, format=fmt, quality=100, subsampling=0)
    else:
        image.save(buffer, format=fmt)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _build_headers(api_key: str, auth_scheme: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not api_key:
        return headers
    scheme = auth_scheme.strip().lower()
    if scheme == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif scheme == "x-api-key":
        headers["X-API-Key"] = api_key
    else:
        headers["Authorization"] = api_key
    return headers


def request_vlm_report(
    *,
    api_url: str,
    api_key: str,
    auth_scheme: str,
    image: Image.Image,
    system_prompt: str,
    user_prompt: str,
    detections: list[dict[str, Any]],
    lat: float | None,
    lon: float | None,
    timeout: float,
    api_type: str = "proprietary",
    model: str = "qwen/qwen2.5-vl-72b-instruct"
) -> dict[str, Any]:
    if api_type == "openai" or "openrouter.ai" in api_url:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_pil_to_base64(image)}"}}
                    ]
                }
            ],
            "response_format": {"type": "json_object"} if "qwen" not in model.lower() else None # Qwen 2.5 VL doesn't always need this but helps
        }
    else:
        payload = {
            "image_b64": encode_pil_to_base64(image),
            "system_prompt": system_prompt,
            "prompt": user_prompt,
            "detections": detections,
            "location": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
            "response_format": "report_markdown_and_severities",
        }

    response = requests.post(
        api_url,
        json=payload,
        headers=_build_headers(api_key, auth_scheme),
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()


    if isinstance(data, dict):
        if "report_markdown" in data or "severities" in data:
            return data
        report = data.get("report")
        if isinstance(report, dict) and ("report_markdown" in report or "severities" in report):
            return report
        text = data.get("text") or data.get("output_text") or data.get("content")
        if isinstance(text, str):
            return {"raw_text": text}

    raise RuntimeError(f"External VLM API returned an unsupported payload shape: {json.dumps(data)[:500]}")
