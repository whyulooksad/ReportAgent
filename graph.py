# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import websockets
from langgraph.graph import END, START, StateGraph

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


def build_graph():
    """
    构建主流程图。

    当前流程：
    START
      -> intent_analysis
      -> template_query_and_split
      -> scheduler
      -> nl2sql
      -> result_review
      -> scheduler / write_report
      -> END
    """
    g = StateGraph(GraphState)

    g.add_node("intent_analysis", intent_analysis_node)
    g.add_node("template_query_and_split", template_query_and_split_node)
    g.add_node("scheduler", scheduler_node)
    g.add_node("nl2sql", nl2sql_node)
    g.add_node("result_review", result_review_node)
    g.add_node("write_report", write_report_node)

    g.add_edge(START, "intent_analysis")
    g.add_edge("intent_analysis", "template_query_and_split")
    g.add_edge("template_query_and_split", "scheduler")
    g.add_conditional_edges(
        "scheduler",
        route_after_scheduler,
        {
            "nl2sql": "nl2sql",
            "write_report": "write_report",
        },
    )
    g.add_edge("nl2sql", "result_review")
    g.add_conditional_edges(
        "result_review",
        route_after_result_review,
        {
            "scheduler": "scheduler",
            "write_report": "write_report",
        },
    )
    g.add_edge("write_report", END)
    return g.compile()


def _state_digest(state: GraphState) -> dict[str, Any]:
    """
    提取一份适合通过 WebSocket 回传的轻量状态摘要。

    不直接返回完整 state，避免前端收到过大的原始结果文本。
    """
    return {
        "iterations": state.get("iterations", 0),
        "meaning": state.get("meaning"),
        "template_name": state.get("template_name"),
        "current_query": state.get("current_query"),
        "remaining_queries": len(state.get("plan") or []),
        "results_count": len(state.get("results") or []),
        "warnings_count": len(state.get("warnings") or []),
        "errors_count": len(state.get("errors") or []),
        "done": state.get("done", False),
    }


async def _send_event(websocket, event_type: str, **payload: Any) -> None:
    """统一封装 WebSocket 事件发送格式。"""
    await websocket.send(json.dumps({"type": event_type, **payload}, ensure_ascii=False))


async def _run_node(
    websocket,
    node_name: str,
    fn: Callable[[GraphState], GraphState],
    state: GraphState,
) -> GraphState:
    """
    执行一个节点，并在开始/结束时分别发送阶段事件。

    这样前端可以实时看到当前跑到哪个阶段，而不是等最终结果一次性返回。
    """
    await _send_event(
        websocket,
        "stage",
        stage=node_name,
        status="started",
        state=_state_digest(state),
    )
    new_state = await asyncio.to_thread(fn, state)
    await _send_event(
        websocket,
        "stage",
        stage=node_name,
        status="completed",
        state=_state_digest(new_state),
    )
    return new_state


async def _execute_with_progress(websocket, init: GraphState) -> GraphState:
    """
    按当前图结构手动驱动执行，并在每个节点后推送阶段事件。

    这里没有改节点逻辑本身，只是把“可观测性”放到了执行层。
    """
    state = await _run_node(websocket, "intent_analysis", intent_analysis_node, init)
    state = await _run_node(
        websocket,
        "template_query_and_split",
        template_query_and_split_node,
        state,
    )
    state = await _run_node(websocket, "scheduler", scheduler_node, state)

    while True:
        route = route_after_scheduler(state)
        if route == "write_report":
            state = await _run_node(websocket, "write_report", write_report_node, state)
            return state

        state = await _run_node(websocket, "nl2sql", nl2sql_node, state)
        state = await _run_node(websocket, "result_review", result_review_node, state)

        review_route = route_after_result_review(state)
        if review_route == "write_report":
            state = await _run_node(websocket, "write_report", write_report_node, state)
            return state

        state = await _run_node(websocket, "scheduler", scheduler_node, state)


async def handle_websocket(websocket):
    """
    处理单个 WebSocket 连接。

    每收到一条用户消息，就初始化一份 GraphState 并执行完整流程，期间持续回传阶段状态。
    """
    print("前端已连接")
    try:
        async for message in websocket:
            user_text = message.strip()
            if not user_text:
                await _send_event(websocket, "error", message="请输入有效的问题")
                continue

            print(f"收到用户输入: {user_text}")
            init: GraphState = {
                "goal": user_text,
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
            await _send_event(websocket, "start", message=user_text)
            final_state = await _execute_with_progress(websocket, init)
            await _send_event(
                websocket,
                "final",
                final_report=final_state.get("final_report", ""),
                state=_state_digest(final_state),
                warnings=final_state.get("warnings", []),
                errors=final_state.get("errors", []),
                evidence_summary=final_state.get("evidence_summary", []),
                outline=final_state.get("outline", []),
            )
    except websockets.exceptions.ConnectionClosed:
        print("前端连接已断开")
    except Exception as e:
        print(f"WebSocket 处理错误: {e}")
        await _send_event(websocket, "error", message=f"处理请求时出错: {str(e)}")


async def start_websocket_server():
    """启动本地 WebSocket 服务。"""
    port = 8080
    server = await websockets.serve(handle_websocket, "localhost", port)
    print(f"WebSocket 服务器启动在: ws://localhost:{port}")
    await server.wait_closed()


if __name__ == "__main__":
    print("启动 WebSocket 服务器模式...")
    try:
        asyncio.run(start_websocket_server())
    except KeyboardInterrupt:
        print("\nWebSocket 服务器已停止")
    except Exception as e:
        print(f"服务器启动失败: {e}")
