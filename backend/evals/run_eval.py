"""Replay the documented offline service contract; no LLM or external API calls.

Run from any directory: python backend/evals/run_eval.py [--output report.json]
The JSON suite expresses scenarios, while focused unit tests cover internals.
"""
import argparse
import asyncio
import copy
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.schemas.food import FoodFilters
from app.services.food_service import FoodService


def require(condition, message):
    if not condition:
        raise AssertionError(message)


async def evaluate_case(case):
    service = FoodService()
    service.amap_service.api_key = ""
    overrides = case.get("record_overrides", {})
    for record in service._local_foods:
        record.update(copy.deepcopy(overrides.get(str(record["id"]), {})))
    constraints = FoodFilters()
    previous_ids, observations = [], []
    for turn_index, turn in enumerate(case["turns"], start=1):
        changes = copy.deepcopy(turn["changes"])
        if turn.get("exclude_previous"):
            changes["exclude_ids"] = list(dict.fromkeys(constraints.exclude_ids + previous_ids))
        constraints = FoodFilters.model_validate({**constraints.model_dump(), **changes})
        before = copy.deepcopy(constraints.model_dump())
        result = await service.search(constraints)
        found, pending = result["results"], result["pending_results"]
        ids, pending_ids = [item["id"] for item in found], [item["id"] for item in pending]
        expected = turn["expected"]
        prefix = f"turn {turn_index}: "
        for key, actual in (("ids", ids), ("pending_ids", pending_ids), ("pending_count", len(pending))):
            if key in expected:
                require(actual == expected[key], prefix + f"{key}: expected {expected[key]!r}, got {actual!r}")
        require(not set(ids).intersection(pending_ids), prefix + "matched and pending sets overlap")
        require(all(item["is_open"] is None for item in found + pending), prefix + "mock opening status presented as fact")
        require(len(found) >= expected.get("minimum_results", 0), prefix + "too few matches")
        for key, value in expected.get("constraints", {}).items():
            require(before[key] == value, prefix + f"lost previous constraint: {key}")
        for item in pending:
            for key in expected.get("pending_constraints", []):
                require(key in item["unknown_constraints"], prefix + f"missing pending explanation: {key}")
        for item in found:
            for key, value in expected.get("all_fields", {}).items():
                require(item.get(key) == value, prefix + f"incorrect provenance: {key}")
            fragment = expected.get("forbidden_taste_fragment")
            if fragment:
                require(all(fragment not in tag for tag in item["taste"]), prefix + "excluded taste present")
            fragment = expected.get("forbidden_cuisine_fragment")
            if fragment:
                require(fragment not in item["cuisine"], prefix + "excluded cuisine present")
        if "forbidden_allergen" in expected:
            require(all(expected["forbidden_allergen"] not in item["allergens"] for item in found + pending),
                    prefix + "known excluded allergen present")
        suggestions = []
        if turn.get("check_suggestions"):
            suggestions = await service.suggest_changes(constraints)
            projected = [{key: suggestion[key] for key in ("id", "changes", "count")} for suggestion in suggestions]
            require(projected == expected.get("suggestions", []), prefix + f"unexpected diagnostics: {projected!r}")
            require(constraints.model_dump() == before, prefix + "diagnostics mutated current constraints")
            for suggestion in suggestions:
                require(not set(suggestion["changes"]).intersection({"exclude_allergens", "exclude_taste", "exclude_cuisines"}),
                        prefix + "diagnostics weakened exclusions")
                changed = FoodFilters.model_validate({**before, **suggestion["changes"]})
                counterfactual = await service.search(changed)
                require(counterfactual["filtered_count"] == suggestion["count"], prefix + "unsupported diagnostic count")
                require(suggestion["count"] > result["filtered_count"], prefix + "diagnostic does not add matches")
        observations.append({"turn": turn_index, "result_ids": ids, "pending_ids": pending_ids,
                             "suggestion_ids": [item["id"] for item in suggestions]})
        previous_ids = ids
    return observations


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--output", type=Path, help="Optional path for the JSON report")
    args = parser.parse_args()
    suite = json.loads(args.cases.read_text(encoding="utf-8"))
    started = time.perf_counter()
    cases = []
    for case in suite["cases"]:
        case_started = time.perf_counter()
        item = {"id": case["id"]}
        try:
            item["observations"] = await evaluate_case(case)
            item["status"] = "passed"
        except Exception as exc:
            item.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        item["elapsed_ms"] = round((time.perf_counter() - case_started) * 1000, 3)
        cases.append(item)
    passed = sum(item["status"] == "passed" for item in cases)
    summary = {
        "suite": suite["suite"], "scope": suite["scope"], "offline": True,
        "model_evaluated": False, "external_calls": 0,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "cases_passed": passed, "cases_failed": len(cases) - passed,
        "cases_total": len(cases), "cases": cases,
    }
    serialized = json.dumps(summary, ensure_ascii=False, indent=2)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
