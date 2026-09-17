"""Small async adapter for compatible chat-completions function calling.

No provider exception text, API keys or endpoint addresses cross this boundary.
Usage belongs to each response so concurrent sessions never share mutable counters.
"""

import json
import math
import os
from typing import Any
from urllib.parse import urlsplit

import httpx


class LLMError(RuntimeError):
    code = "model_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class LLMUnavailableError(LLMError):
    code = "model_unavailable"


class LLMTimeoutError(LLMError):
    code = "model_timeout"


class LLMProtocolError(LLMError):
    code = "model_invalid_response"


class LLMRequestError(LLMError):
    code = "model_request_failed"


class LLMService:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model_id: str | None = None,
        timeout: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url if base_url is not None else os.getenv("LLM_BASE_URL", "https://api.deepseek.com")).strip().rstrip("/")
        self._api_key = (api_key if api_key is not None else os.getenv("LLM_API_KEY", "")).strip()
        self._model_id = (model_id if model_id is not None else os.getenv("LLM_MODEL_ID", "deepseek-chat")).strip()
        self._transport = transport
        self._config_valid = self._validate_config()
        try:
            timeout = float(timeout)
            self._timeout = min(20.0, max(0.1, timeout)) if math.isfinite(timeout) else 15.0
        except (ValueError, TypeError):
            self._timeout = 15.0

    def _validate_config(self) -> bool:
        try:
            parsed = urlsplit(self._base_url)
            valid_url = bool(
                parsed.scheme in {"http", "https"} and parsed.hostname
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
                and not any(char.isspace() or ord(char) < 32 for char in self._base_url)
            )
            # Accessing port also validates malformed and out-of-range port strings.
            parsed.port
            return valid_url and len(self._base_url) <= 2048 and len(self._model_id) <= 200 and not any(
                ord(char) < 32 for char in self._api_key + self._model_id
            )
        except (ValueError, TypeError):
            return False

    def status(self) -> dict:
        if not self._api_key or not self._model_id or not self._base_url:
            return {"available": False, "reason": "not_configured"}
        if not self._config_valid:
            return {"available": False, "reason": "invalid_configuration"}
        return {"available": True, "reason": "ready"}

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
    ) -> dict:
        if not self.status()["available"]:
            raise LLMUnavailableError()
        self._validate_messages(messages)
        payload: dict[str, Any] = {
            "model": self._model_id,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1500,
            "stream": False,
        }
        if tools:
            if len(tools) > 8:
                raise LLMProtocolError()
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=self._timeout, follow_redirects=False,
            ) as client:
                response = await client.post(
                    self._base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + self._api_key},
                    json=payload,
                )
            response.raise_for_status()
            if len(response.content) > 512000:
                raise LLMProtocolError()
            result = response.json()
        except httpx.TimeoutException:
            raise LLMTimeoutError() from None
        except httpx.HTTPError:
            raise LLMRequestError() from None
        except (ValueError, TypeError, RecursionError):
            raise LLMProtocolError() from None
        return self._parse_response(result)

    @staticmethod
    def _validate_messages(messages: list[dict]) -> None:
        if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
            raise LLMProtocolError()
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
                raise LLMProtocolError()
            content = message.get("content")
            if content is not None and (not isinstance(content, str) or len(content) > 64000):
                raise LLMProtocolError()
        try:
            if len(json.dumps(messages, ensure_ascii=False, allow_nan=False)) > 200000:
                raise LLMProtocolError()
        except (ValueError, TypeError, RecursionError):
            raise LLMProtocolError() from None

    @staticmethod
    def _parse_response(result: Any) -> dict:
        try:
            if not isinstance(result, dict):
                raise LLMProtocolError()
            choices = result.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise LLMProtocolError()
            choice = choices[0]
            if choice.get("finish_reason") in {"length", "content_filter"}:
                raise LLMProtocolError()
            raw_message = choice.get("message")
            if not isinstance(raw_message, dict) or raw_message.get("role") != "assistant":
                raise LLMProtocolError()
            content = raw_message.get("content")
            if content is not None and (not isinstance(content, str) or len(content) > 64000):
                raise LLMProtocolError()
            message: dict[str, Any] = {"role": "assistant", "content": content}
            calls = raw_message.get("tool_calls")
            if calls is not None:
                if not isinstance(calls, list) or not 1 <= len(calls) <= 6:
                    raise LLMProtocolError()
                clean_calls = []
                seen_ids: set[str] = set()
                for call in calls:
                    if not isinstance(call, dict) or call.get("type") != "function":
                        raise LLMProtocolError()
                    call_id = call.get("id")
                    function = call.get("function")
                    if not isinstance(call_id, str) or not 1 <= len(call_id) <= 128 or call_id in seen_ids or not isinstance(function, dict):
                        raise LLMProtocolError()
                    name, arguments = function.get("name"), function.get("arguments")
                    if not isinstance(name, str) or not 1 <= len(name) <= 80 or not isinstance(arguments, str) or len(arguments) > 16000:
                        raise LLMProtocolError()
                    seen_ids.add(call_id)
                    clean_calls.append({"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}})
                message["tool_calls"] = clean_calls
            if not content and not calls:
                raise LLMProtocolError()
            raw_usage = result.get("usage") or {}
            usage = {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = raw_usage.get(key, 0) if isinstance(raw_usage, dict) else 0
                usage[key] = value if type(value) is int and 0 <= value <= 100000000 else 0
            return {"message": message, "usage": usage}
        except (KeyError, IndexError, TypeError, AttributeError, RecursionError):
            raise LLMProtocolError() from None
