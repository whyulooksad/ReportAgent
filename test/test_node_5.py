# -*- coding: utf-8 -*-
from __future__ import annotations

import json
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


from node import result_review_node
from state import GraphState


def _make_state(query: str, result: str) -> GraphState:
    return {
        "goal": "测试节点5",
        "plan": [],
        "current_query": None,
        "results": [{"query": query, "result": result}],
        "iterations": 1,
        "done": False,
        "final_report": "",
        "all_queries_snapshot": [query],
        "meaning": "query",
        "template_name": None,
        "template_text": None,
        "report_type": None,
        "time": None,
        "region": None,
        "query_tasks": [],
        "errors": [],
        "warnings": [],
        "evidence_summary": [],
        "outline": [query],
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


def _run_with_mode(query: str, result: str, mode: str) -> GraphState:
    state = _make_state(query, result)

    if mode == "real":
        return result_review_node(state)

    if mode == "fallback":
        with patch("node._get_llm_client", side_effect=RuntimeError("forced fallback")):
            return result_review_node(state)

    if mode == "mock":
        status = input("请输入要模拟的状态 [ok/empty/error]，默认 ok: ").strip().lower() or "ok"
        if status not in {"ok", "empty", "error"}:
            raise ValueError(f"Unknown mock status: {status}")
        fake_content = json.dumps(
            {"status": status, "needs_follow_up": status in {"empty", "error"}},
            ensure_ascii=False,
        )
        with patch("node._get_llm_client", return_value=(_FakeLLM(fake_content), "fake-model")):
            return result_review_node(state)

    raise ValueError(f"Unknown mode: {mode}")


def main() -> None:
    print("节点5交互测试")
    print("模式说明：real=真实调用LLM，mock=模拟LLM成功返回，fallback=强制走启发式回退")
    mode = input("请输入模式 [real/mock/fallback]，默认 mock: ").strip().lower() or "mock"
    query = input("请输入一条 query: ").strip()
    result = input("请输入这条 query 的 result: ").strip()

    if not query:
        print("query 为空，结束。")
        return

    print("\n[输入状态]")
    pprint(_make_state(query, result))

    print("\n[执行中]")
    new_state = _run_with_mode(query, result, mode)

    print("\n[节点5输出状态]")
    pprint(new_state)

    print("\n[关键字段]")
    summary = {
        "latest_evidence": (new_state.get("evidence_summary") or [None])[-1],
        "warnings": new_state.get("warnings"),
        "errors": new_state.get("errors"),
        "plan": new_state.get("plan"),
        "done": new_state.get("done"),
    }
    pprint(summary)

    print("\n[结论]")
    latest = (new_state.get("evidence_summary") or [{}])[-1]
    print(f"节点5判定为：{latest.get('status')}")
    print(f"本次测试模式：{mode}")
    print("说明：当前节点5不会自动补查，也不会回插 plan。")
    if mode == "real":
        print("说明：如果控制台上方出现 fallback 日志，则本次实际走的是启发式回退，不是真实 LLM 成功返回。")


if __name__ == "__main__":
    main()
