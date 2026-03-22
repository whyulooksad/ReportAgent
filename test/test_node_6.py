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


from helper import route_after_result_review, route_after_scheduler
from node import (
    intent_analysis_node,
    nl2sql_node,
    result_review_node,
    scheduler_node,
    template_query_and_split_node,
    write_report_node,
)
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
    if not os.getenv("DASHSCOPE_APIKEY"):
        raise RuntimeError("缺少 DASHSCOPE_APIKEY，无法调用真实 LLM。")

    nl2sql_url = os.getenv("NL2SQL_URL", "http://localhost:8001/nl2sql")
    print(f"当前 NL2SQL_URL: {nl2sql_url}")


def _state_digest(state: GraphState) -> dict:
    return {
        "meaning": state.get("meaning"),
        "report_type": state.get("report_type"),
        "time": state.get("time"),
        "region": state.get("region"),
        "template_name": state.get("template_name"),
        "outline_count": len(state.get("outline") or []),
        "query_tasks_count": len(state.get("query_tasks") or []),
        "remaining_plan_count": len(state.get("plan") or []),
        "current_query": state.get("current_query"),
        "results_count": len(state.get("results") or []),
        "warnings_count": len(state.get("warnings") or []),
        "errors_count": len(state.get("errors") or []),
        "done": state.get("done"),
    }


def _print_stage(name: str, state: GraphState) -> None:
    print(f"\n[{name}]")
    pprint(_state_digest(state))


def _run_full(goal: str) -> GraphState:
    state = _make_state(goal)

    _print_stage("初始状态", state)

    state = intent_analysis_node(state)
    _print_stage("节点1 intent_analysis", state)

    state = template_query_and_split_node(state)
    _print_stage("节点2 template_query_and_split", state)

    state = scheduler_node(state)
    _print_stage("节点3 scheduler", state)

    round_idx = 1
    while True:
        route = route_after_scheduler(state)
        if route == "write_report":
            break

        print(f"\n[查询轮次 {round_idx}]")
        state = nl2sql_node(state)
        _print_stage("节点4 nl2sql", state)

        state = result_review_node(state)
        _print_stage("节点5 result_review", state)

        review_route = route_after_result_review(state)
        if review_route == "write_report":
            break

        state = scheduler_node(state)
        _print_stage("节点3 scheduler", state)
        round_idx += 1

    state = write_report_node(state)
    _print_stage("节点6 write_report", state)
    return state


def _print_final_summary(state: GraphState) -> None:
    print("\n[最终摘要]")
    pprint(
        {
            "meaning": state.get("meaning"),
            "template_name": state.get("template_name"),
            "report_type": state.get("report_type"),
            "time": state.get("time"),
            "region": state.get("region"),
            "query_count": len(state.get("all_queries_snapshot") or []),
            "results_count": len(state.get("results") or []),
            "warnings": state.get("warnings"),
            "errors": state.get("errors"),
            "evidence_count": len(state.get("evidence_summary") or []),
            "final_report_len": len(state.get("final_report") or ""),
        }
    )

    print("\n[最终报告]")
    report = (state.get("final_report") or "").strip()
    if not report:
        print("未生成 final_report。")
    else:
        print(report)


def main() -> None:
    print("节点1 到 节点6 真实联调测试")
    print("说明：本脚本不做 mock，会真实调用意图分析、模板规划、NL2SQL、结果检查和报告写作。")
    print("前置条件：")
    print("- 已配置 DASHSCOPE_APIKEY")
    print("- NL2SQL 服务已启动")
    print("推荐输入示例：")
    print("- 生成今天的四川省水情日报")
    print("- 生成2026年3月四川省水情月报")

    goal = input("请输入一条请求，默认 生成今天的四川省水情日报: ").strip() or "生成今天的四川省水情日报"

    _validate_env()
    final_state = _run_full(goal)
    _print_final_summary(final_state)


if __name__ == "__main__":
    main()
