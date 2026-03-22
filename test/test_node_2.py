# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from pprint import pprint


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


try:
    import openai  # noqa: F401
except Exception:
    fake_openai = types.ModuleType("openai")

    class _DummyOpenAI:
        def __init__(self, *args, **kwargs) -> None:
            pass

    fake_openai.OpenAI = _DummyOpenAI
    sys.modules["openai"] = fake_openai


from node import intent_analysis_node, template_query_and_split_node
from state import GraphState


def _make_state(goal: str) -> GraphState:
    return {
        "goal": goal,
        "plan": [],
        "current_query": None,
        "results": [],
        "iterations": 0,
        "done": False,
        "final_report": "",
        "all_queries_snapshot": [],
        "meaning": None,
        "template_name": None,
        "template_text": None,
        "report_type": None,
        "time": None,
        "region": None,
        "query_tasks": [],
        "errors": [],
        "warnings": [],
        "evidence_summary": [],
        "outline": [],
        "review_retry_counts": {},
    }


def _validate_env() -> None:
    api_key = os.getenv("DASHSCOPE_APIKEY")
    if not api_key:
        raise RuntimeError("缺少 DASHSCOPE_APIKEY，无法调用真实 LLM。")


def _run_full(goal: str) -> tuple[GraphState, GraphState]:
    state0 = _make_state(goal)
    state1 = intent_analysis_node(state0)
    state2 = template_query_and_split_node(state1)
    return state1, state2


def _print_observation_notes(state1: GraphState, state2: GraphState) -> None:
    plan = state2.get("plan") or []
    warnings = state2.get("warnings") or []
    query_tasks = state2.get("query_tasks") or []

    print("\n[人工检查项]")
    print(f"- 节点1是否识别为 report: {'是' if state1.get('meaning') == 'report' else '否'}")
    print(f"- 是否提取出报告类型: {'是' if state1.get('report_type') else '否'}")
    print(f"- 是否提取出时间: {'是' if state1.get('time') else '否'}")
    print(f"- 是否提取出地区: {'是' if state1.get('region') else '否'}")
    print(f"- 节点2是否命中模板: {'是' if state2.get('template_name') else '否'}")
    print(f"- 节点2是否生成 outline: {'是' if state2.get('outline') else '否'}")
    print(f"- 节点2是否生成 query_tasks: {'是' if query_tasks else '否'}")
    print(f"- 节点2是否生成 plan: {'是' if plan else '否'}")

    if warnings:
        print("- 当前 warnings:")
        for item in warnings:
            print(f"  - {item}")

    if not plan:
        print("- 结果说明: 这版节点2已经没有本地降级。")
        print("  只要模板缺失、schema 不完整，或者 LLM 没生成有效 queries，plan 就可能为空。")


def _print_summary(goal: str, state1: GraphState, state2: GraphState) -> None:
    plan = state2.get("plan") or []

    print("\n[节点1关键信息]")
    pprint(
        {
            "goal": goal,
            "meaning": state1.get("meaning"),
            "report_type": state1.get("report_type"),
            "time": state1.get("time"),
            "region": state1.get("region"),
        }
    )

    print("\n[节点2关键信息]")
    pprint(
        {
            "template_name": state2.get("template_name"),
            "report_type": state2.get("report_type"),
            "time": state2.get("time"),
            "region": state2.get("region"),
            "outline": state2.get("outline"),
            "query_tasks_count": len(state2.get("query_tasks") or []),
            "plan_count": len(plan),
            "warnings": state2.get("warnings"),
        }
    )

    print("\n[节点2查询计划]")
    if not plan:
        print("未生成查询计划。")
    for idx, item in enumerate(plan, start=1):
        print(f"{idx}. {item}")

    print("\n[节点2查询任务]")
    if not state2.get("query_tasks"):
        print("未生成 query_tasks。")
    for item in state2.get("query_tasks") or []:
        pprint(item)

    _print_observation_notes(state1, state2)


def main() -> None:
    print("节点1 + 节点2 真实联调测试")
    print("说明：本脚本不做 mock，直接调用真实节点1和节点2。")
    print("说明：节点2当前已经移除了本地降级，真实输出会完全反映 LLM + 模板 + schema 的效果。")
    print("推荐输入示例：")
    print("- 生成今天的四川省水情日报")
    print("- 生成2026年3月四川省水情月报")
    goal = input("请输入一条报告请求，默认 生成今天的四川省水情日报: ").strip() or "生成今天的四川省水情日报"

    _validate_env()

    print("\n[初始状态]")
    pprint(_make_state(goal))

    print("\n[执行中]")
    state1, state2 = _run_full(goal)

    print("\n[节点1完整输出]")
    pprint(state1)

    print("\n[节点2完整输出]")
    pprint(state2)

    _print_summary(goal, state1, state2)


if __name__ == "__main__":
    main()
