"""Agent acceptance tests: real local retrieval, scripted model decisions, no network."""

import asyncio
import copy
import inspect
import json
import time
import unittest
from collections import deque
from uuid import uuid4

import httpx
from fastapi import FastAPI

from app.agents.food_agent import FoodAgent
from app.routes.chat import router
from app.schemas.chat import ChatRequest
from app.services.food_service import FoodService
from app.services.llm_service import LLMTimeoutError
from app.services.session_service import SessionError, SessionStore


def function_result(name, arguments):
    return {"message": {"role": "assistant", "content": None, "tool_calls": [{
        "id": str(uuid4()), "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }]}, "usage": {"total_tokens": 10}}


def intent(**changes):
    return function_result("interpret_request", changes)


def answer(*ids):
    return function_result("submit_food_answer", {"recommendations": [
        {"food_id": food_id, "evidence_fields": ["avg_price", "campus_area"]} for food_id in ids
    ]})


def update(field, value, evidence):
    return {"field": field, "value": value, "evidence": evidence}


class ScriptedLLM:
    def __init__(self, *responses, available=True):
        self.responses = deque(responses)
        self.available = available
        self.calls = []

    def status(self):
        return {"available": self.available, "reason": "ready" if self.available else "not_configured"}

    async def complete(self, messages, tools=None, tool_choice="auto"):
        self.calls.append(copy.deepcopy({"messages": messages, "tools": tools, "tool_choice": tool_choice}))
        if not self.responses:
            raise AssertionError("Unexpected model call")
        result = self.responses.popleft()
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            result = result()
        if inspect.isawaitable(result):
            result = await result
        return copy.deepcopy(result)


class FoodAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.foods = FoodService()
        self.foods.amap_service.api_key = ""
        self.llm = ScriptedLLM()
        self.store = SessionStore()
        self.agent = FoodAgent(self.foods, self.llm, self.store)

    async def seed(self, **filters):
        return await self.agent.chat(ChatRequest(ui_changes=filters))

    def next_request(self, previous, message="", **changes):
        return ChatRequest(session_id=previous["session_id"],
                           expected_state_version=previous["state_version"],
                           message=message, **changes)

    async def test_natural_language_two_turns_preserve_constraints_and_replace(self):
        first_message = "晚饭想在食堂吃清淡点，人均15元以内"
        self.llm.responses.extend([
            intent(updates=[update("meal_time", "晚餐", "晚饭"),
                            update("campus_area", "学校食堂", "食堂"),
                            update("taste", ["清淡"], "清淡"),
                            update("max_price", 15, "人均15元以内")]), answer("local:2"),
            intent(updates=[update("max_price", 20, "预算可以到20元")], replace_previous=True), answer("local:9"),
        ])
        first = await self.agent.chat(ChatRequest(message=first_message))
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["recommended_ids"], ["local:2"])
        second = await self.agent.chat(self.next_request(first, "换一家，预算可以到20元"))
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["recommended_ids"], ["local:9"])
        self.assertEqual(second["constraints"]["campus_area"], "学校食堂")
        self.assertEqual(second["constraints"]["taste"], ["清淡"])
        self.assertEqual(second["constraints"]["meal_time"], "晚餐")
        self.assertEqual(second["constraints"]["max_price"], 20)
        self.assertEqual(second["constraints"]["exclude_ids"], ["local:2"])
        self.assertEqual(second["state_version"], 2)
        self.assertEqual(second["metrics"]["model_calls"], 2)
        self.assertEqual(second["metrics"]["total_tokens"], 20)

    async def test_unconfigured_model_preserves_state_and_form_works(self):
        self.llm.available = False
        initial = await self.seed(max_price=15, campus_area="学校食堂")
        self.assertEqual(initial["status"], "completed")
        response = await self.agent.chat(self.next_request(initial, "预算改为20元"))
        self.assertEqual(response["status"], "unavailable")
        self.assertEqual(response["constraints"]["max_price"], 15)
        self.assertEqual(response["state_version"], initial["state_version"])
        self.assertEqual(self.llm.calls, [])

    async def test_invalid_candidate_is_never_returned_and_uses_grounded_fallback(self):
        self.llm.responses.extend([intent(updates=[update("max_price", 15, "15元")]), answer("invented-restaurant")])
        result = await self.agent.chat(ChatRequest(message="预算15元"))
        self.assertEqual(result["status"], "degraded")
        self.assertNotIn("invented-restaurant", result["recommended_ids"])
        self.assertTrue(result["foods"])
        self.assertTrue(all(food["avg_price"] <= 15 for food in result["foods"]))
        self.assertIn({"tool": "output_validation", "status": "invalid_input"}, result["tool_events"])

    async def test_unknown_tool_and_condition_override_rejected(self):
        for tool, arguments in [("execute_shell", {"command": "do not run"}), ("search_foods", {"max_price": 100})]:
            with self.subTest(tool=tool):
                llm = ScriptedLLM(intent(updates=[update("max_price", 10, "10元")]), function_result(tool, arguments))
                result = await FoodAgent(self.foods, llm).chat(ChatRequest(message="预算10元"))
                self.assertEqual(result["status"], "degraded")
                self.assertEqual(result["constraints"]["max_price"], 10)
                self.assertTrue(all(food["avg_price"] <= 10 for food in result["foods"]))

    async def test_invalid_intent_is_clarified_without_partial_commit(self):
        initial = await self.seed(max_price=15, taste=["清淡"])
        self.llm.responses.append(intent(updates=[update("max_price", 100, "预算100元")]))
        result = await self.agent.chat(self.next_request(initial, "换个推荐"))
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["constraints"], initial["constraints"])
        self.assertEqual(result["recommended_ids"], initial["recommended_ids"])

    async def test_clarification_supplement_can_complete_original_request(self):
        self.llm.responses.extend([
            intent(clarification="想吃清淡还是辣？"),
            intent(updates=[update("max_price", 15, "每人15元"), update("taste", ["清淡"], "清淡")]),
            answer("local:2"),
        ])
        first = await self.agent.chat(ChatRequest(message="帮我推荐晚餐，想吃清淡还是辣？"))
        self.assertEqual(first["status"], "needs_clarification")
        second = await self.agent.chat(self.next_request(first, "选清淡，每人15元"))
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["constraints"]["taste"], ["清淡"])
        self.assertEqual(second["constraints"]["max_price"], 15)
        self.assertEqual(self.store.get(second["session_id"]).pending_message, "")

    async def test_missing_reference_is_clarified(self):
        initial = await self.seed(campus_area="学校食堂", max_price=15, taste=["清淡"])
        self.llm.responses.append(intent(action="details", reference_indices=[3]))
        result = await self.agent.chat(self.next_request(initial, "第三家怎么样"))
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["recommended_ids"], initial["recommended_ids"])

    async def test_clarification_keeps_verified_partial_conditions(self):
        self.llm.responses.extend([
            intent(updates=[update("meal_time", "晚餐", "晚餐"),
                            update("campus_area", "学校食堂", "食堂")], clarification="需要预算"),
            intent(updates=[update("max_price", 15, "人均15元"), update("taste", ["清淡"], "清淡")]),
            answer("local:2"),
        ])
        first = await self.agent.chat(ChatRequest(message="食堂晚餐，预算没想好"))
        second = await self.agent.chat(self.next_request(first, "人均15元，清淡"))
        self.assertEqual(second["constraints"]["meal_time"], "晚餐")
        self.assertEqual(second["constraints"]["campus_area"], "学校食堂")
        self.assertEqual(second["recommended_ids"], ["local:2"])

    async def test_compare_and_details_use_displayed_order(self):
        initial = await self.seed(campus_area="学校食堂", max_price=20)
        ids = initial["recommended_ids"][:2]
        self.llm.responses.extend([intent(action="compare", reference_indices=[1, 2]), answer(*ids)])
        result = await self.agent.chat(self.next_request(initial, "比较第一家和第二家"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["recommended_ids"], ids)
        self.assertEqual(result["tool_events"][0]["tool"], "compare_foods")

    async def test_details_cannot_silently_switch_to_another_candidate(self):
        initial = await self.seed(campus_area="学校食堂", max_price=20)
        self.llm.responses.extend([intent(action="details", reference_indices=[2]), answer(initial["recommended_ids"][0])])
        result = await self.agent.chat(self.next_request(initial, "第二家怎么样"))
        self.assertEqual(result["recommended_ids"], [initial["recommended_ids"][1]])

    async def test_empty_result_suggests_without_mutating_budget_or_dietary_exclusions(self):
        self.llm.responses.extend([intent(), answer()])
        result = await self.agent.chat(ChatRequest(message="推荐晚饭", ui_changes={"max_price": 1, "exclude_taste": ["辣"]}))
        self.assertEqual(result["recommended_ids"], [])
        self.assertEqual(result["constraints"]["max_price"], 1)
        self.assertEqual(result["constraints"]["exclude_taste"], ["辣"])
        self.assertTrue(all("exclude_taste" not in suggestion["changes"] for suggestion in result["suggested_changes"]))

    async def test_allergen_unknowns_are_never_selected_as_confirmed(self):
        self.llm.responses.extend([intent(updates=[update("exclude_allergens", ["花生"], "花生过敏")]), answer()])
        result = await self.agent.chat(ChatRequest(message="花生过敏，请推荐"))
        self.assertEqual(result["foods"], [])
        self.assertTrue(result["pending_results"])
        self.assertEqual(result["constraints"]["exclude_allergens"], ["花生"])

    async def test_explicit_cancellation_can_clear_budget(self):
        initial = await self.seed(max_price=10)
        self.llm.responses.extend([intent(clear=[{"field": "max_price", "evidence": "取消预算限制"}]), answer()])
        result = await self.agent.chat(self.next_request(initial, "取消预算限制"))
        self.assertIsNone(result["constraints"]["max_price"])

    async def test_negated_budget_cancellation_must_preserve_budget(self):
        initial = await self.seed(max_price=10)
        self.llm.responses.extend([intent(clear=[{"field": "max_price", "evidence": "不要取消预算限制"}]), answer()])
        result = await self.agent.chat(self.next_request(initial, "不要取消预算限制"))
        self.assertEqual(result["constraints"]["max_price"], 10)

    async def test_negated_numeric_update_must_preserve_budget(self):
        initial = await self.seed(max_price=10)
        self.llm.responses.extend([intent(updates=[update("max_price", 100, "预算不要改到100元")]), answer()])
        result = await self.agent.chat(self.next_request(initial, "预算不要改到100元"))
        self.assertEqual(result["constraints"]["max_price"], 10)

    async def test_negated_area_must_not_be_selected(self):
        initial = await self.seed(campus_area="学校食堂")
        self.llm.responses.extend([intent(updates=[update("campus_area", "南门", "不要南门")]), answer()])
        result = await self.agent.chat(self.next_request(initial, "不要南门"))
        self.assertEqual(result["constraints"]["campus_area"], "学校食堂")

    async def test_clearing_one_excluded_allergen_must_not_clear_other_allergens(self):
        initial = await self.seed(exclude_allergens=["花生", "海鲜"])
        self.llm.responses.extend([intent(clear=[{"field": "exclude_allergens", "evidence": "取消花生过敏限制"}]), answer()])
        result = await self.agent.chat(self.next_request(initial, "取消花生过敏限制"))
        self.assertIn("海鲜", result["constraints"]["exclude_allergens"])

    async def test_clearing_one_excluded_cuisine_must_not_clear_other_exclusions(self):
        initial = await self.seed(exclude_cuisines=["火锅", "烧烤"])
        self.llm.responses.extend([intent(clear=[{"field": "exclude_cuisines", "evidence": "取消火锅限制"}]), answer()])
        result = await self.agent.chat(self.next_request(initial, "取消火锅限制"))
        self.assertIn("烧烤", result["constraints"]["exclude_cuisines"])

    async def test_negated_replacement_does_not_exclude_displayed_restaurants(self):
        initial = await self.seed(max_price=15)
        self.llm.responses.extend([intent(replace_previous=True), answer()])
        result = await self.agent.chat(self.next_request(initial, "不要换一家"))
        self.assertEqual(result["constraints"]["exclude_ids"], initial["constraints"]["exclude_ids"])

    async def test_negated_spicy_preference_is_not_added_as_positive(self):
        initial = await self.seed()
        self.llm.responses.extend([intent(updates=[update("taste", ["辣"], "不要辣")]), answer()])
        result = await self.agent.chat(self.next_request(initial, "不要辣"))
        self.assertNotIn("辣", result["constraints"]["taste"])

    async def test_rejected_negation_cannot_be_reused_from_pending_message_to_relax_budget(self):
        initial = await self.seed(max_price=10)
        self.llm.responses.extend([
            intent(updates=[update("max_price", 100, "100元")]),
            intent(updates=[update("max_price", 100, "100元")]), answer(),
        ])
        first = await self.agent.chat(self.next_request(initial, "预算不要改到100元"))
        self.assertEqual(first["constraints"]["max_price"], 10)
        second = await self.agent.chat(self.next_request(first, "保持原样"))
        self.assertEqual(second["constraints"]["max_price"], 10)

    async def test_ambiguous_group_budget_requires_clarification_even_if_model_misses_it(self):
        initial = await self.seed(max_price=15)
        self.llm.responses.extend([intent(updates=[update("max_price", 60, "预算60元")]), answer()])
        result = await self.agent.chat(self.next_request(initial, "我们3个人，预算60元"))
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["constraints"]["max_price"], 15)

    async def test_unsupported_claim_uses_stable_capability_message(self):
        self.llm.responses.append(intent(unsupported="live_opening"))
        result = await self.agent.chat(ChatRequest(message="现在还开门吗"))
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("没有可靠的实时营业信息", result["reply"])
        self.assertEqual(result["foods"], [])

    async def test_intent_timeout_and_provider_error_preserve_original_state(self):
        initial = await self.seed(max_price=15)
        self.llm.responses.append(LLMTimeoutError())
        result = await self.agent.chat(self.next_request(initial, "预算改为20元"))
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["constraints"], initial["constraints"])
        self.assertEqual(result["state_version"], initial["state_version"])

    async def test_outer_timeout_rolls_back_provisional_changes(self):
        initial = await self.seed(max_price=15)
        self.agent.timeout = 0.03

        async def hang():
            await asyncio.Event().wait()

        self.llm.responses.extend([intent(updates=[update("max_price", 20, "预算20元")]), hang])
        result = await self.agent.chat(self.next_request(initial, "预算20元"))
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["constraints"], initial["constraints"])
        self.assertEqual(result["state_version"], initial["state_version"])
        self.assertFalse(self.store.get(initial["session_id"]).lock.locked())

    async def test_client_cancellation_does_not_commit_partial_turn(self):
        initial = await self.seed(max_price=15)
        entered = asyncio.Event()

        async def hang():
            entered.set()
            await asyncio.Event().wait()

        self.llm.responses.extend([intent(updates=[update("max_price", 20, "预算20元")]), hang])
        task = asyncio.create_task(self.agent.chat(self.next_request(initial, "预算20元")))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        session = self.store.get(initial["session_id"])
        self.assertEqual(session.filters.max_price, 15)
        self.assertEqual(session.version, initial["state_version"])
        self.assertFalse(session.lock.locked())

    async def test_first_request_retry_is_idempotent(self):
        request = ChatRequest(ui_changes={"max_price": 15})
        first = await self.agent.chat(request)
        repeated = await self.agent.chat(request)
        self.assertEqual(first, repeated)
        self.assertEqual(len(self.store.sessions), 1)

    async def test_replayed_request_is_idempotent_without_extra_model_calls(self):
        initial = await self.seed(max_price=15)
        self.llm.responses.extend([intent(), answer()])
        request = self.next_request(initial, "推荐几家")
        first = await self.agent.chat(request)
        second = await self.agent.chat(request)
        self.assertEqual(first, second)
        self.assertEqual(len(self.llm.calls), 2)
        self.assertEqual(self.store.get(initial["session_id"]).version, first["state_version"])

    async def test_duplicate_request_id_with_changed_body_is_conflict(self):
        initial = await self.seed(max_price=15)
        request = self.next_request(initial, request_id="same-request", ui_changes={"max_price": 20})
        await self.agent.chat(request)
        changed = request.model_copy(update={"ui_changes": {"max_price": 25}})
        with self.assertRaises(SessionError) as context:
            await self.agent.chat(changed)
        self.assertEqual(context.exception.detail["code"], "request_conflict")
        self.assertEqual(self.store.get(initial["session_id"]).filters.max_price, 20)

    async def test_stale_and_missing_version_rejected(self):
        initial = await self.seed(max_price=15)
        for version in (0, None):
            with self.subTest(version=version):
                request = ChatRequest(session_id=initial["session_id"], expected_state_version=version, ui_changes={"max_price": 50})
                with self.assertRaises(SessionError) as context:
                    await self.agent.chat(request)
                self.assertEqual(context.exception.detail["code"], "state_conflict")

    async def test_simultaneous_turns_on_same_version_cannot_overwrite(self):
        initial = await self.seed(max_price=15)
        entered, release = asyncio.Event(), asyncio.Event()

        async def gated_intent():
            entered.set()
            await release.wait()
            return intent(updates=[update("max_price", 20, "预算20元")])

        self.llm.responses.extend([gated_intent, answer()])
        first_task = asyncio.create_task(self.agent.chat(self.next_request(initial, "预算20元")))
        await asyncio.wait_for(entered.wait(), 1)
        second_task = asyncio.create_task(self.agent.chat(self.next_request(initial, ui_changes={"max_price": 100})))
        await asyncio.sleep(0)
        release.set()
        first = await first_task
        with self.assertRaises(SessionError) as context:
            await second_task
        self.assertEqual(context.exception.detail["code"], "state_conflict")
        self.assertEqual(first["constraints"]["max_price"], 20)

    async def test_browser_sessions_do_not_share_constraints_or_candidates(self):
        first = await self.seed(campus_area="学校食堂", max_price=10)
        second = await self.seed(campus_area="南门", max_price=30)
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual(self.store.get(first["session_id"]).filters.max_price, 10)
        self.assertTrue(all(food["campus_area"] == "学校食堂" for food in first["foods"]))
        self.assertTrue(all(food["campus_area"] == "南门" for food in second["foods"]))

    async def test_endpoint_conflicts_and_invalid_filters_are_structured(self):
        app = FastAPI()
        app.include_router(router)
        app.state.food_agent = self.agent
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local.test") as client:
            response = await client.post("/api/chat", json={"ui_changes": {"max_price": 15}})
            self.assertEqual(response.status_code, 200)
            initial = response.json()
            conflict = await client.post("/api/chat", json={"session_id": initial["session_id"], "expected_state_version": 0})
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["detail"]["code"], "state_conflict")
            invalid = await client.post("/api/chat", json={"session_id": initial["session_id"], "expected_state_version": 1, "ui_changes": {"max_price": -1}})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(self.store.get(initial["session_id"]).version, 1)

    def test_expired_sessions_and_capacity_are_bounded(self):
        store = SessionStore(ttl=1, max_sessions=1)
        session = store.get()
        with self.assertRaises(SessionError) as context:
            store.get()
        self.assertEqual(context.exception.detail["code"], "session_capacity")
        session.touched_at = time.monotonic() - 2
        with self.assertRaises(SessionError) as context:
            store.get(session.id)
        self.assertEqual(context.exception.detail["code"], "session_expired")
        self.assertNotEqual(store.get().id, session.id)


if __name__ == "__main__":
    unittest.main()
