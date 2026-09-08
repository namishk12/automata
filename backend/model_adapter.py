"""OpenAI-compatible model adapter usable with hosted or local endpoints."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .schemas import ModelSettings, ModelSettingsUpdate
from .storage import Storage


class ModelError(RuntimeError):
    pass


def _clean_endpoint(endpoint: str) -> str:
    value = endpoint.rstrip("/")
    return value[: -len("/chat/completions")] if value.endswith("/chat/completions") else value


def _parse_json_content(content: Any) -> dict[str, Any]:
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
    if not isinstance(content, str):
        raise ModelError("The model returned an unsupported content format.")
    candidate = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ModelError(f"The model response was not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ModelError("The model response must be a JSON object.")
    return parsed


class ModelAdapter:
    def __init__(self, settings: ModelSettings, api_key: str | None = None) -> None:
        self.settings = settings
        self.api_key = api_key or ""

    @classmethod
    def from_storage(cls, storage: Storage) -> "ModelAdapter":
        endpoint = os.getenv("AUTOMATA_MODEL_ENDPOINT") or storage.get_setting("model_endpoint", "https://api.openai.com/v1")
        model = os.getenv("AUTOMATA_MODEL_NAME") or storage.get_setting("model_name", "gpt-4o-mini")
        timeout = int(os.getenv("AUTOMATA_MODEL_TIMEOUT", storage.get_setting("model_timeout", 45)))
        supports_images = bool(storage.get_setting("model_supports_images", False))
        supports_structured = bool(storage.get_setting("model_supports_structured", True))
        api_key = os.getenv("AUTOMATA_MODEL_API_KEY") or storage.get_setting("model_api_key", "")
        source = "environment" if any(os.getenv(name) for name in ["AUTOMATA_MODEL_ENDPOINT", "AUTOMATA_MODEL_NAME", "AUTOMATA_MODEL_API_KEY"]) else "database"
        if not endpoint and not model:
            source = "default"
        settings = ModelSettings(
            endpoint=endpoint,
            model=model,
            timeout_seconds=timeout,
            supports_images=supports_images,
            supports_structured_output=supports_structured,
            api_key_configured=bool(api_key),
            source=source,
        )
        return cls(settings, api_key)

    def public_settings(self) -> ModelSettings:
        return self.settings

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        image_data_url: str | None = None,
    ) -> dict[str, Any]:
        content: Any = user_prompt
        if image_data_url and self.settings.supports_images:
            content = [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
        }
        if self.settings.supports_structured_output:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{_clean_endpoint(self.settings.endpoint)}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ModelError(f"Could not reach the model endpoint: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:500].replace("\n", " ")
            raise ModelError(f"Model endpoint returned HTTP {response.status_code}: {detail}")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise ModelError("The model endpoint returned an unexpected response shape.") from exc
        return _parse_json_content(content)

    async def test_connection(self) -> dict[str, Any]:
        result = await self.complete_json(
            "Return only JSON with the boolean key ok.",
            '{"ok":true}',
        )
        return {"ok": bool(result.get("ok", True)), "model": self.settings.model, "endpoint": _clean_endpoint(self.settings.endpoint)}

    @staticmethod
    def update_storage(storage: Storage, update: ModelSettingsUpdate) -> None:
        storage.set_setting("model_endpoint", update.endpoint)
        storage.set_setting("model_name", update.model)
        storage.set_setting("model_timeout", update.timeout_seconds)
        storage.set_setting("model_supports_images", update.supports_images)
        storage.set_setting("model_supports_structured", update.supports_structured_output)
        if update.api_key is not None:
            # The key is never included in API responses, logs, exports, or frontend code.
            storage.set_setting("model_api_key", update.api_key)
