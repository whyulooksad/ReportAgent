# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from pprint import pprint
from types import SimpleNamespace
from unittest.mock import patch


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


from node import intent_analysis_node
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
        "report_type": None,
        "time": None,
        "errors": [],
        "warnings": [],
        "evidence_summary": [],
        "outline": [],
        "review_retry_counts": {},
    }


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


def _guess_regex_intent(goal: str) -> str:
    text = (goal or "").strip()
    if not text:
        return "other"
    if re.search(r"(生成|撰写|写.{0,8}(报告|快报|周报|月报|简报|通报)|水情(报告|快报|周报|月报))", text):
        return "report"
    if re.search(r"(查询|多少|最大|最小|水位|雨量|流量|涨水|超警|监测站|站点)", text):
        return "query"
    if re.search(r"(报告|快报|周报|月报|简报|通报)", text):
        return "report"
    return "query"


def _run_with_mode(goal: str, mode: str) -> GraphState:
    state = _make_state(goal)

    if mode == "real":
        return intent_analysis_node(state)

    if mode == "fallback":
        with patch("node._get_llm_client", side_effect=RuntimeError("forced fallback")):
            return intent_analysis_node(state)

    if mode == "mock":
        intent = _guess_regex_intent(goal)
        fake_content = json.dumps({"intent": intent}, ensure_ascii=False)
        with patch("node._get_llm_client", return_value=(_FakeLLM(fake_content), "fake-model")):
            return intent_analysis_node(state)

    raise ValueError(f"Unknown mode: {mode}")


def _detect_execution_path(mode: str, new_state: GraphState) -> str:
    if mode == "fallback":
        return "fallback-regex"
    if mode == "mock":
        return "mock-llm"
    if new_state.get("meaning") in {"query", "report", "other"}:
        return "real-llm-or-fallback"
    return "unknown"


def main() -> None:
    print("节点1交互测试")
    print("模式说明：real=真实调用LLM，mock=模拟LLM成功返回，fallback=强制走正则回退")
    mode = input("请输入模式 [real/mock/fallback]，默认 mock: ").strip().lower() or "mock"
    goal = input("请输入一条用户请求: ").strip()

    if not goal:
        print("输入为空，结束。")
        return

    print("\n[输入状态]")
    pprint(_make_state(goal))

    print("\n[执行中]")
    new_state = _run_with_mode(goal, mode)

    print("\n[节点1输出状态]")
    pprint(new_state)

    print("\n[关键字段]")
    summary = {
        "meaning": new_state.get("meaning"),
        "plan": new_state.get("plan"),
        "all_queries_snapshot": new_state.get("all_queries_snapshot"),
        "outline": new_state.get("outline"),
        "time": new_state.get("time"),
        "done": new_state.get("done"),
    }
    pprint(summary)

    print("\n[结论]")
    print(f"节点1判定为：{new_state.get('meaning')}")
    print(f"本次测试模式：{mode}")
    print(f"执行路径说明：{_detect_execution_path(mode, new_state)}")
    if mode == "real":
        print("说明：如果控制台上方出现 fallback 日志，则本次实际走的是正则回退，不是真实 LLM 成功返回。")


if __name__ == "__main__":
    main()
