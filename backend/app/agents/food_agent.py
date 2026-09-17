"""A bounded tool-calling agent with server-owned constraints and grounded replies."""
import asyncio
import copy
import hashlib
import json
import logging
import re
import time
from uuid import uuid4

from pydantic import ValidationError

from app.agents.prompts import (
    AGENT_SYSTEM_PROMPT, FINAL_ANSWER_TOOL, INTENT_SYSTEM_PROMPT, INTERPRET_TOOL,
)
from app.agents.tools import TOOLS, validate_tool_call
from app.schemas.chat import FinalAnswer, InterpretedRequest
from app.schemas.food import FoodFilters
from app.services.llm_service import LLMService
from app.services.session_service import SessionError, SessionStore

logger = logging.getLogger("uvicorn.error")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class ClarificationNeeded(Exception):
    pass


class FoodAgent:
    def __init__(self, foods, llm=None, sessions=None, timeout=20):
        self.foods = foods
        self.llm = llm or LLMService()
        self.sessions = sessions or SessionStore()
        self.timeout = timeout

    def status(self):
        available = self.llm.status()["available"]
        return {
            "configured": available,
            "mode": "llm" if available else "unavailable",
            "message": "模型服务已配置" if available else
                       "对话尚未就绪，请在 backend/.env 配置模型服务。表单筛选仍可使用。",
        }

    async def chat(self, request):
        session = self.sessions.get(request.session_id, request_id=request.request_id)
        fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        started = time.monotonic()
        async with session.lock:
            session.touched_at = time.monotonic()
            if request.request_id in session.requests:
                old_fingerprint, response = session.requests[request.request_id]
                if old_fingerprint != fingerprint:
                    raise SessionError("request_conflict", "请求编号已使用，请重新提交。", session)
                return copy.deepcopy(response)
            if request.session_id and request.expected_state_version != session.version:
                raise SessionError("state_conflict", "条件已更新，请同步后重新提交。", session)
            try:
                async with asyncio.timeout(self.timeout):
                    response = await self._turn(request, session)
            except ClarificationNeeded as exc:
                session.pending_message = (session.pending_message + "\n" + request.message).strip()[-2000:]
                session.version += 1
                response = self._base(session, "needs_clarification", str(exc))
                response["clarification"] = str(exc)
            except TimeoutError:
                response = self._base(session, "degraded", "本次对话超时，已保留原有条件。请重试或使用筛选。")
            except ValidationError:
                raise
            except Exception:
                # Never serialize transport exceptions: they may contain keys or URLs.
                logger.warning("agent_turn_failed", extra={"session_id": session.id})
                response = self._base(session, "degraded", "模型暂时不可用，已保留原有条件。请重试或使用筛选。")
            response["trace_id"] = str(uuid4())
            response.setdefault("metrics", {})["latency_ms"] = round((time.monotonic() - started) * 1000)
            session.remember_response(request.request_id, fingerprint, response)
            logger.info("agent_turn trace=%s status=%s calls=%s latency_ms=%s",
                        response["trace_id"], response["status"],
                        response["metrics"].get("model_calls", 0), response["metrics"]["latency_ms"])
            return response

    def _base(self, session, status, reply):
        foods = [session.candidates[key] for key in session.displayed_ids if key in session.candidates]
        response = dict(status=status, session_id=session.id, state_version=session.version,
                    reply=reply, constraints=session.filters.model_dump(),
                    recommended_ids=[f["id"] for f in foods], foods=copy.deepcopy(foods),
                    reasons=[], unknowns=[], pending_results=[], suggested_changes=[],
                    clarification=None, tool_events=[], filtered_count=len(foods),
                    total_candidates=len(session.candidates), using_realtime=any(not f.get("is_mock", True) for f in foods))
        response.update(copy.deepcopy(session.result_meta))
        return response

    async def _turn(self, request, session):
        filters = FoodFilters.model_validate({**session.filters.model_dump(), **session.pending_changes,
                                             **(request.ui_changes or {})})
        message = request.message.strip()
        events, metrics = [], {"model_calls": 0, "total_tokens": 0}
        intent = None
        if message:
            if not self.llm.status()["available"]:
                return self._base(session, "unavailable", self.status()["message"])
            if re.search(r"(?:[2-9]\d*|两|二|三|四|五|六|七|八|九|十)\s*(?:个)?人", message) and re.search(r"预算|\d+\s*元", message):
                if not re.search(r"人均|每人", message):
                    raise ClarificationNeeded("多人用餐请说明每人预算，例如“每人 20 元”；当前筛选使用人均参考价。")
            if re.search(r"步行|走路|走过去|走到", message) and re.search(r"分钟|多久|多远|以内", message):
                raise ClarificationNeeded("目前只有参考距离，还无法验证从你的位置出发的步行时间。可以先按区域或人均预算筛选。")
            if re.search(r"现在|此刻|实时", message) and re.search(r"营业|开门|开着", message):
                raise ClarificationNeeded("目前没有可靠的实时营业信息，无法确认此刻是否开门。可以查看餐厅的参考营业时段。")
            context = dict(message=message, pending_message=session.pending_message,
                           constraints=filters.model_dump(), displayed_ids=session.displayed_ids,
                           displayed_foods=[{"id": key, "name": session.candidates[key]["name"]}
                                            for key in session.displayed_ids if key in session.candidates],
                           history=session.history[-6:])
            result = await self._complete([
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": json_text(context)},
            ], [INTERPRET_TOOL], metrics, {"type": "function", "function": {"name": "interpret_request"}})
            try:
                calls = result.get("tool_calls", [])
                if len(calls) != 1 or calls[0]["function"]["name"] != "interpret_request":
                    raise ValueError("Intent missing")
                intent = InterpretedRequest.model_validate_json(calls[0]["function"]["arguments"])
                if intent.clarification:
                    partial = self._apply_intent(filters, intent, message, session)
                    session.pending_changes = {
                        key: value for key, value in partial.model_dump().items()
                        if value != session.filters.model_dump()[key]
                    }
                    # Use a stable prompt: arbitrary model prose is not user-facing evidence.
                    raise ClarificationNeeded("请补充人均预算、区域或具体餐厅；多人用餐时，请说明预算是总计还是每人。")
                if intent.unsupported != "none":
                    descriptions = {
                        "walking_route": "目前只有参考距离，还无法验证从你的位置出发的步行时间。可以先按区域或人均预算筛选。",
                        "live_opening": "目前没有可靠的实时营业信息，无法确认此刻是否开门。可以查看餐厅的参考营业时段。",
                        "dietary_claim": "目前只有餐厅级参考数据，无法验证具体菜品的营养、配料或过敏安全。可以按已记录信息筛选。",
                    }
                    raise ClarificationNeeded(descriptions[intent.unsupported])
                filters = self._apply_intent(filters, intent, message, session)
            except (ValidationError, ValueError, KeyError, TypeError):
                raise ClarificationNeeded("没有可靠地理解本次条件，请换种说法，或直接在筛选区修改。")
            except ClarificationNeeded:
                raise

        # Everything below operates on a private turn snapshot. Commit occurs at the end.
        candidates = copy.deepcopy(session.candidates) if filters == session.filters else {}
        selected = [i for i in session.displayed_ids if i in candidates]
        search_result = None
        suggestions = []
        invalid_output = False
        action = intent.action if intent else "search"
        if intent and intent.replace_previous:
            action = "search"
        reference_ids = []
        if intent and intent.reference_indices:
            for index in intent.reference_indices:
                if index > len(session.displayed_ids):
                    raise ClarificationNeeded("当前列表中没有这个序号，请指出餐厅名称或重新获取推荐。")
                reference_ids.append(session.displayed_ids[index - 1])
        scoped_ids = None

        async def execute(name, args):
            nonlocal candidates, selected, search_result, suggestions
            if name == "search_foods":
                if scoped_ids is not None:
                    raise ValueError("A detail/comparison turn is scoped to its snapshot")
                search_result = await self.foods.search(filters)
                candidates = {f["id"]: f for f in search_result["results"]}
                selected = list(candidates)[:3] if message else list(candidates)
                result = {"status": "ok" if selected else "empty", **search_result}
            elif name in ("get_food_details", "compare_foods"):
                ids = args["food_ids"]
                if any(food_id not in candidates or (scoped_ids is not None and food_id not in scoped_ids) for food_id in ids):
                    raise ValueError("Entity outside current snapshot")
                selected = ids
                result = {"status": "ok", "foods": [candidates[key] for key in ids]}
            else:
                suggestions = await self.foods.suggest_changes(filters)
                result = {"status": "ok" if suggestions else "empty", "suggested_changes": suggestions}
            events.append({"tool": name, "status": result["status"]})
            return result

        # Run the selected first action under server-owned filters; it cannot broaden them.
        first_tool, args = "search_foods", {}
        if candidates and action in ("details", "explain", "compare"):
            ids = reference_ids or selected[:(3 if action == "compare" else 1)]
            if action == "compare" and len(ids) < 2:
                raise ClarificationNeeded("比较需要至少两家餐厅，请先调整条件获取更多候选。")
            first_tool = "compare_foods" if action == "compare" else "get_food_details"
            args = {"food_ids": ids}
            scoped_ids = set(ids)
        initial_observation = await execute(first_tool, args)
        if message:
            messages = [
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": json_text({
                    "message": message, "action": action, "constraints": filters.model_dump(),
                    "reference_ids": reference_ids, "history": session.history[-6:],
                    "initial_tool": first_tool, "observation": initial_observation,
                })},
            ]
            completed = False
            calls_count = 1
            for _ in range(3):
                try:
                    assistant = await self._complete(messages, TOOLS + [FINAL_ANSWER_TOOL], metrics)
                    tool_calls = assistant.get("tool_calls") or []
                    if not tool_calls:
                        invalid_output = True
                        break
                    messages.append({"role": "assistant", "content": assistant.get("content"), "tool_calls": tool_calls})
                    for call in tool_calls:
                        name = call["function"]["name"]
                        if name == FINAL_ANSWER_TOOL["function"]["name"]:
                            answer = FinalAnswer.model_validate_json(call["function"]["arguments"])
                            ids = [rec.food_id for rec in answer.recommendations]
                            if len(set(ids)) != len(ids) or any(key not in candidates or (scoped_ids is not None and key not in scoped_ids) for key in ids):
                                raise ValueError("Ungrounded output")
                            if ids:
                                selected = ids
                            completed = True
                            break
                        if calls_count >= 6:
                            raise ValueError("Tool budget exhausted")
                        arguments = validate_tool_call(name, call["function"]["arguments"])
                        observation = await execute(name, arguments)
                        calls_count += 1
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": json_text(observation)[:16000]})
                    if completed:
                        break
                except (ValueError, ValidationError, KeyError, TypeError):
                    invalid_output = True
                    events.append({"tool": "output_validation", "status": "invalid_input"})
                    break
                except Exception:
                    invalid_output = True
                    events.append({"tool": "model", "status": "unavailable"})
                    break
            if not completed:
                invalid_output = True

        if not selected and not suggestions and len(events) < 6:
            suggestions = await self.foods.suggest_changes(filters)
            events.append({"tool": "suggest_constraint_changes", "status": "ok" if suggestions else "empty"})
        if action == "suggest" and not suggestions and len(events) < 6:
            suggestions = await self.foods.suggest_changes(filters)
            events.append({"tool": "suggest_constraint_changes", "status": "ok" if suggestions else "empty"})
        foods = [candidates[key] for key in selected if key in candidates]
        reasons = [{"food_id": food["id"], "text": self._reason(food)} for food in foods]
        if foods:
            if action == "compare":
                reply = "按当前记录比较：\n" + "\n".join(f"{f['name']}：{self._reason(f)}" for f in foods)
            elif action in ("details", "explain"):
                reply = "依据本轮查询记录：\n" + "\n".join(f"{f['name']}：{self._reason(f)}" for f in foods)
            else:
                reply = f"按当前条件找到 {search_result['filtered_count'] if search_result else len(foods)} 家，展示 {len(foods)} 家。"
                reply += "可以继续说“换一家”或调整预算。" if message else "可以继续修改筛选条件。"
            if any(f.get("is_mock") for f in foods):
                reply += "\n其中本地记录为模拟数据，价格仅供参考。"
        else:
            reply = "当前数据中没有已确认符合全部条件的餐厅。可以查看待确认信息，或选择下面的条件调整。"
        if invalid_output:
            reply += "\n模型未完成有效答复，已展示经过规则校验的查询结果。"

        session.filters = filters
        session.candidates = candidates
        session.displayed_ids = selected
        session.pending_message = ""
        session.pending_changes = {}
        session.version += 1
        if search_result:
            session.result_meta = {key: copy.deepcopy(search_result[key]) for key in (
                "unknowns", "pending_results", "filtered_count", "total_candidates", "using_realtime")}
        if message:
            session.history = (session.history + [{"role": "user", "content": message},
                                                  {"role": "assistant", "content": reply}])[-8:]
        response = self._base(session, "degraded" if invalid_output else "completed", reply)
        response.update(reasons=reasons, tool_events=events, metrics=metrics,
                        suggested_changes=suggestions)
        if search_result:
            for key in ("unknowns", "pending_results", "filtered_count", "total_candidates", "using_realtime"):
                response[key] = search_result.get(key, response.get(key))
        return response

    async def _complete(self, messages, tools, metrics, tool_choice="auto"):
        metrics["model_calls"] += 1
        result = await self.llm.complete(messages, tools=tools, tool_choice=tool_choice)
        metrics["total_tokens"] += result.get("usage", {}).get("total_tokens", 0)
        return result["message"]

    def _apply_intent(self, filters, intent, message, session):
        values = filters.model_dump()
        # Evidence can only authorize a change when quoted from this turn. Pending
        # text is context for the model, never proof for a later mutation.
        evidence_text = message
        for update in intent.updates:
            evidence = update.evidence.strip()
            if not evidence or evidence not in evidence_text:
                raise ClarificationNeeded("请明确要修改的筛选条件。")
            if update.field not in ("exclude_allergens", "exclude_taste", "exclude_cuisines", "exclude_ids"):
                # Negated commands are not authorization to broaden a hard condition.
                if re.search(r"别|不要|不能|不可|不想|不去|不改|不换|不取消|不提高|不增加|不降低", message):
                    if update.field in ("max_price", "max_distance", "min_rating", "campus_area", "meal_time"):
                        raise ClarificationNeeded("为避免误改条件，请明确要保留或修改哪项，也可以直接使用筛选区。")
            # A numeric relaxation must be supported by an actual number in the user's words.
            if update.field in ("max_price", "max_distance", "min_rating", "limit"):
                numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", evidence)]
                numeric_words = {"max_price": r"预算|元|块|人均|价|到|至", "max_distance": r"距离|米",
                                 "min_rating": r"评分|分", "limit": r"家|个|数量"}
                if (type(update.value) not in (int, float) or update.value not in numbers
                        or not re.search(numeric_words[update.field], evidence)):
                    raise ClarificationNeeded("请使用数字明确人均预算、参考距离或评分，例如“预算改为 20 元”。")
            elif update.field in ("taste", "exclude_taste", "exclude_allergens", "exclude_cuisines"):
                if not isinstance(update.value, list) or not update.value:
                    raise ClarificationNeeded("如需移除口味或禁忌，请明确说明取消哪项条件。")
                for value in update.value:
                    if not isinstance(value, str) or not (value in evidence or (
                            update.field == "exclude_taste" and "辣" in value and re.search(r"不.*辣|不要.*辣", evidence))):
                        raise ClarificationNeeded("请明确口味或需要排除的食材、类型。")
                if update.field == "taste":
                    if re.search(r"不要|不吃|不想|不能|不辣|别", evidence) or any(
                        re.search(r"(?:不要|不吃|不想|不能|别|避开)\s*(?:吃)?\s*" + re.escape(value), message)
                        for value in update.value
                    ):
                        raise ClarificationNeeded("已保留原口味条件。若需要排除辣味，请在筛选区选择“不吃辣”。")
                    values["taste"] = list(dict.fromkeys(values["taste"] + update.value))
                    continue
            elif update.field == "campus_area":
                area_words = {"学校食堂": "食堂", "南门": "南门", "西门龙湖时代天街": "西门|龙湖|天街"}
                if update.value not in area_words or not re.search(area_words[update.value], evidence):
                    raise ClarificationNeeded("请选择学校食堂、南门或西门龙湖时代天街。")
            elif update.field == "meal_time":
                aliases = {"早餐": "早餐|早饭", "午餐": "午餐|午饭", "晚餐": "晚餐|晚饭", "夜宵": "夜宵|宵夜"}
                if update.value not in aliases or not re.search(aliases[update.value], evidence):
                    raise ClarificationNeeded("请明确早餐、午餐、晚餐或夜宵。")
            elif update.field == "sort_by":
                aliases = {"price": "便宜|价格|预算", "rating": "评分|好评", "reference_distance": "距离|近"}
                if update.value not in aliases or not re.search(aliases[update.value], evidence):
                    raise ClarificationNeeded("请选择按评分、人均参考价或参考距离排序。")
            elif update.field == "exclude_ids":
                raise ClarificationNeeded("可以说“换一家”，或通过页面排除某家餐厅。")
            elif update.field == "keywords":
                if not isinstance(update.value, str) or not update.value or update.value not in evidence:
                    raise ClarificationNeeded("请明确要搜索的餐厅名称或类型。")
            if update.field in ("exclude_allergens", "exclude_taste", "exclude_cuisines", "exclude_ids"):
                if not isinstance(update.value, list):
                    raise ClarificationNeeded("请明确需要排除的内容。")
                values[update.field] = list(dict.fromkeys(values[update.field] + update.value))
            else:
                values[update.field] = update.value
        field_words = {
            "max_price": r"预算|价格|金额", "max_distance": r"距离", "min_rating": r"评分",
            "campus_area": r"区域|校区|食堂|南门|西门", "meal_time": r"时段|早餐|午餐|晚餐|夜宵",
            "taste": r"口味", "keywords": r"关键词|搜索", "exclude_allergens": r"过敏|忌口",
            "exclude_taste": r"口味|辣", "exclude_cuisines": r"菜系|类型|火锅",
            "exclude_ids": r"排除|换家|餐厅", "sort_by": r"排序", "limit": r"数量",
        }
        defaults = FoodFilters().model_dump()
        for clear in intent.clear:
            evidence = clear.evidence.strip()
            if (not evidence or evidence not in message or
                    re.search(r"别|不要|不能|不可|不想|不取消|不清除|不重置", message) or
                    not re.search(r"取消|不限|清除|重置|不限制|恢复", evidence) or
                    not (re.search(field_words[clear.field], evidence) or (
                        isinstance(values[clear.field], list) and any(item in evidence for item in values[clear.field])))):
                raise ClarificationNeeded("如需取消条件，请明确说明，例如“取消预算限制”。")
            if clear.field in ("exclude_allergens", "exclude_taste", "exclude_cuisines", "exclude_ids"):
                if re.search(r"所有|全部", evidence):
                    values[clear.field] = []
                else:
                    values[clear.field] = [item for item in values[clear.field] if item not in evidence]
            else:
                values[clear.field] = defaults[clear.field]
        if intent.replace_previous:
            if not re.search(r"换一家|换一批|换几家|换个|其他家|别.*刚才|不要.*刚才", message):
                raise ClarificationNeeded("请明确是否要排除刚才推荐的餐厅。")
            if re.search(r"不要\s*(换|换一家|换一批)|不(?:要|想)换", message):
                raise ClarificationNeeded("已保留当前推荐；如需更换，请直接说“换一家”。")
            values["exclude_ids"] = list(dict.fromkeys(values["exclude_ids"] + session.displayed_ids))
        return FoodFilters.model_validate(values)

    @staticmethod
    def _reason(food):
        parts = [food.get("campus_area", "区域未知")]
        price = food.get("avg_price")
        parts.append(f"人均参考 ¥{price:g}" if isinstance(price, (int, float)) else "价格待确认")
        if food.get("taste"):
            parts.append("记录口味：" + "、".join(food["taste"]))
        if food.get("rating") is not None:
            parts.append(f"参考评分 {food['rating']:g}")
        parts.append("实时营业及过敏原信息未核实")
        return "；".join(parts)
