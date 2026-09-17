"""Provider boundary tests run entirely locally using httpx.MockTransport."""

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from app.agents.prompts import FINAL_ANSWER_TOOL, INTERPRET_TOOL
from app.agents.tools import TOOLS, ToolValidationError, validate_tool_call
from app.schemas.chat import ChatRequest, FinalAnswer, InterpretedRequest
from app.services.llm_service import (
    LLMProtocolError,
    LLMRequestError,
    LLMService,
    LLMTimeoutError,
    LLMUnavailableError,
)


def response_body(content="ready", **overrides):
    result = {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": content,
    }}], "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}}
    result.update(overrides)
    return result


def service(handler, **kwargs):
    config = {"base_url": "https://model.example/v1", "api_key": "secret-test-key", "model_id": "test-model"}
    config.update(kwargs)
    return LLMService(transport=httpx.MockTransport(handler), **config)


class LLMServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_function_call_protocol_and_per_response_usage(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=response_body(None, choices=[{
                "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "reasoning_content": "do not expose",
                    "tool_calls": [{"id": "call_1", "type": "function", "function": {
                        "name": "search_foods", "arguments": "{}",
                    }}],
                },
            }]))

        llm = service(handler)
        result = await llm.complete([{"role": "user", "content": "推荐晚饭"}], tools=TOOLS)
        self.assertEqual(str(seen[0].url), "https://model.example/v1/chat/completions")
        self.assertEqual(seen[0].headers["authorization"], "Bearer secret-test-key")
        payload = json.loads(seen[0].content)
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["tools"], TOOLS)
        self.assertEqual(result["usage"]["total_tokens"], 14)
        self.assertNotIn("reasoning_content", result["message"])
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["name"], "search_foods")

    async def test_endpoint_without_v1_and_named_choice(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=response_body())

        llm = service(handler, base_url="https://api.deepseek.com/")
        choice = {"type": "function", "function": {"name": "interpret_request"}}
        await llm.complete([{"role": "user", "content": "hello"}], [INTERPRET_TOOL], choice)
        self.assertEqual(str(seen[0].url), "https://api.deepseek.com/chat/completions")
        self.assertEqual(json.loads(seen[0].content)["tool_choice"], choice)

    async def test_missing_configuration_never_calls_network(self):
        def handler(request):
            self.fail("An unconfigured model must never send a request")

        llm = service(handler, api_key="")
        self.assertEqual(llm.status(), {"available": False, "reason": "not_configured"})
        with self.assertRaises(LLMUnavailableError) as context:
            await llm.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(str(context.exception), "model_unavailable")

    async def test_local_compatible_endpoint_can_use_dummy_key(self):
        llm = service(lambda request: httpx.Response(200, json=response_body()),
                      base_url="http://127.0.0.1:11434/v1", api_key="local")
        self.assertTrue(llm.status()["available"])
        self.assertEqual((await llm.complete([{"role": "user", "content": "hello"}]))["message"]["content"], "ready")

    async def test_bad_endpoint_rejected_and_status_redacted(self):
        for endpoint in ["file:///etc/passwd", "ftp://host", "https://user:secret@host/v1",
                         "https://host/v1?api_key=secret", "https://host/v1#fragment",
                         "https://host:99999", "https://ho st/v1", "not-a-url"]:
            with self.subTest(endpoint=endpoint):
                llm = service(lambda request: self.fail("Invalid URL used"), base_url=endpoint)
                self.assertEqual(llm.status(), {"available": False, "reason": "invalid_configuration"})
                with self.assertRaises(LLMUnavailableError):
                    await llm.complete([{"role": "user", "content": "hello"}])
                self.assertNotIn(endpoint, json.dumps(llm.status()))

    async def test_provider_errors_do_not_leak_url_key_or_body(self):
        for status in (401, 429, 500, 302):
            with self.subTest(status=status):
                llm = service(lambda request: httpx.Response(status, text="secret-test-key private provider detail"))
                with self.assertRaises(LLMRequestError) as context:
                    await llm.complete([{"role": "user", "content": "hello"}])
                self.assertEqual(str(context.exception), "model_request_failed")
                self.assertNotIn("secret", repr(context.exception))

    async def test_timeout_and_connection_errors_are_sanitized(self):
        def timeout(request):
            raise httpx.ReadTimeout("secret-test-key https://private-host", request=request)

        def unavailable(request):
            raise httpx.ConnectError("secret-test-key https://private-host", request=request)

        for handler, expected in [(timeout, LLMTimeoutError), (unavailable, LLMRequestError)]:
            with self.subTest(expected=expected):
                with self.assertRaises(expected) as context:
                    await service(handler).complete([{"role": "user", "content": "hello"}])
                self.assertNotIn("secret", str(context.exception))
                self.assertNotIn("private-host", str(context.exception))

    async def test_invalid_json_response_rejected(self):
        llm = service(lambda request: httpx.Response(200, text="<html>secret detail</html>"))
        with self.assertRaises(LLMProtocolError):
            await llm.complete([{"role": "user", "content": "hello"}])

    async def test_malformed_or_truncated_response_rejected(self):
        malformed = [None, [], {}, {"choices": []}, response_body(None),
                     response_body(choices=[{"message": {"role": "system", "content": "bad"}}]),
                     response_body(choices=[{"finish_reason": "length", "message": {"role": "assistant", "content": "truncated"}}]),
                     response_body(choices=[{"message": {"role": "assistant", "content": [], "tool_calls": []}}]),
                     response_body(choices=[{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function", "function": {"name": "search_foods", "arguments": {}}}]}}])]
        for body in malformed:
            with self.subTest(body=body):
                llm = service(lambda request: httpx.Response(200, json=body))
                with self.assertRaises(LLMProtocolError):
                    await llm.complete([{"role": "user", "content": "hello"}])

    async def test_duplicate_calls_and_unbounded_inputs_rejected(self):
        call = {"id": "same", "type": "function", "function": {"name": "search_foods", "arguments": "{}"}}
        llm = service(lambda request: httpx.Response(200, json=response_body(choices=[{
            "message": {"role": "assistant", "content": None, "tool_calls": [call, call]},
        }])))
        with self.assertRaises(LLMProtocolError):
            await llm.complete([{"role": "user", "content": "hello"}])
        for messages in ([], [{"role": "user", "content": "hello"}] * 41,
                         [{"role": "unknown", "content": "hello"}],
                         [{"role": "user", "content": "x" * 64001}]):
            with self.subTest(messages_length=len(messages)):
                with self.assertRaises(LLMProtocolError):
                    await llm.complete(messages)

    async def test_concurrent_calls_keep_usage_separate(self):
        async def handler(request):
            count = int(json.loads(request.content)["messages"][0]["content"])
            await asyncio.sleep(0)
            return httpx.Response(200, json=response_body(str(count), usage={"total_tokens": count}))

        llm = service(handler)
        results = await asyncio.gather(*[
            llm.complete([{"role": "user", "content": str(number)}]) for number in (12, 35)
        ])
        self.assertEqual([result["usage"]["total_tokens"] for result in results], [12, 35])
        self.assertFalse(hasattr(llm, "last_usage"))

    async def test_cancellation_propagates_to_outer_deadline(self):
        async def handler(request):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await service(handler).complete([{"role": "user", "content": "hello"}])

    def test_timeout_capped_and_defaults_from_environment(self):
        with patch.dict("os.environ", {"LLM_BASE_URL": "https://api.deepseek.com", "LLM_API_KEY": "test", "LLM_MODEL_ID": "deepseek-chat"}):
            llm = LLMService(timeout=600)
            self.assertTrue(llm.status()["available"])
            self.assertEqual(llm._timeout, 20)


class AgentContractTests(unittest.TestCase):
    def test_registry_rejects_unknown_or_condition_overrides(self):
        self.assertEqual(validate_tool_call("search_foods", "{}"), {})
        self.assertEqual(validate_tool_call("get_food_details", {"food_ids": ["local:2"]}), {"food_ids": ["local:2"]})
        invalid = [("execute_python", "{}"), ("search_foods", '{"max_price":100}'),
                   ("search_foods", "[]"), ("search_foods", "not JSON"),
                   ("compare_foods", '{"food_ids":["local:2"]}'),
                   ("get_food_details", '{"food_ids":[2]}'),
                   ("get_food_details", '{"food_ids":["local:2","local:2"]}')]
        for name, arguments in invalid:
            with self.subTest(name=name, arguments=arguments):
                with self.assertRaises(ToolValidationError):
                    validate_tool_call(name, arguments)

    def test_wire_schema_rejects_extra_fields_and_invalid_values(self):
        self.assertEqual(ChatRequest().message, "")
        for body in ({"session_id": "not-uuid"}, {"message": "x" * 2001}, {"message": 12},
                     {"expected_state_version": -1}, {"expected_state_version": True},
                     {"arbitrary": "field"}, {"ui_changes": {str(i): i for i in range(21)}}):
            with self.subTest(body_keys=list(body)):
                with self.assertRaises(ValidationError):
                    ChatRequest.model_validate(body)
        with self.assertRaises(ValidationError):
            InterpretedRequest.model_validate({"updates": [{"field": "max_price", "value": 20, "evidence": ""}]})
        for indices in ([0], [21], [1, 1], ["2"], [True]):
            with self.subTest(indices=indices):
                with self.assertRaises(ValidationError):
                    InterpretedRequest.model_validate({"reference_indices": indices})
        with self.assertRaises(ValidationError):
            FinalAnswer.model_validate({"recommendations": [{"food_id": "local:2", "reason": "made-up fact"}]})

    def test_function_schemas_are_standalone_and_closed(self):
        for tool in [INTERPRET_TOOL, FINAL_ANSWER_TOOL, *TOOLS]:
            encoded = json.dumps(tool)
            self.assertNotIn("$ref", encoded)
            self.assertNotIn("$defs", encoded)
            self.assertEqual(tool["type"], "function")
            self.assertFalse(tool["function"]["parameters"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
