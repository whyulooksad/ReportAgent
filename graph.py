# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import re
from typing import TypedDict, Optional, List, Any, Literal, Dict
import requests
from datetime import datetime, timedelta
from langgraph.graph import StateGraph, START, END
import asyncio
import websockets

import report_writer
import template_planner

# ===================== 可配置服务地址 =====================
# 仅 NL2SQL 独立作为服务，其余（question/report）在本进程内编排执行。
NL2SQL_URL = os.getenv("NL2SQL_URL", "http://localhost:8001/nl2sql")

# ===================== 状态类型 =====================
class GraphState(TypedDict):
    """
    有向图（LangGraph）在各节点之间传递的统一状态结构。
    """
    goal: str                        # 用户目标（原始自然语言需求）
    plan: List[str]                  # 待执行的 NL 查询问题列表（会被逐个弹出执行）
    current_query: Optional[str]     # 当前正在执行的 NL 查询（从 plan 中弹出）
    results: List[Dict[str, str]]    # NL2SQL 的执行结果列表（顺序与执行顺序一致）
    iterations: int                  # 已执行的查询次数（用于调试或防御）
    done: bool                       # 是否已无查询可执行
    final_report: str                # 最终输出（meaning=="report" 时为报告；"query" 为 NL2SQL 结果汇总）
    all_queries_snapshot: List[str]  # 全量查询问题的快照（用于打印与调试）
    meaning: Optional[str]           # main_question 判断出的意图：query / report / other
    template_name: Optional[str]     # main_question 选中的模板名（可选）
    report_type: Optional[str]       # 报告类型（可选）
    time: Optional[str]              # 时间范围/日期（可选）

# ===================== 相对日期替换 =====================
def _fmt(d: datetime) -> str:
    """将日期格式化为 YYYY-MM-DD 字符串。"""
    return d.strftime("%Y-%m-%d")

def _resolve_relative_dates(text: str, base: Optional[datetime] = None) -> str:
    """
    将中文相对日期（如“今天/昨天/明天/今天到明天”）替换为**绝对日期**，提高可复现性。
    - 仅做轻量规则替换，不涉及复杂自然语言时间解析。
    - base 默认为当前时间。
    """
    if not text:
        return text
    base = base or datetime.now()
    d_today = base.date()
    d_yday  = (base - timedelta(days=1)).date()
    d_tmr   = (base + timedelta(days=1)).date()

    s_today = _fmt(datetime.combine(d_today, datetime.min.time()))
    s_yday  = _fmt(datetime.combine(d_yday,  datetime.min.time()))
    s_tmr   = _fmt(datetime.combine(d_tmr,   datetime.min.time()))

    out = text
    # 常见“今天到明天”的范围表达
    out = re.sub(r"今天(到|至)明天", f"{s_today}到{s_tmr}", out)
    # 单点替换
    out = out.replace("昨天", s_yday).replace("昨日", s_yday)
    out = out.replace("今天", s_today).replace("今日", s_today)
    out = out.replace("明天", s_tmr)
    return out


def _guess_intent(user_input: str) -> str:
    text = (user_input or "").strip()
    if not text:
        return "other"
    if re.search(r"(生成|撰写|写|出).{0,8}(报告|快报|周报|月报|简报|通报)|水情(报告|快报|周报|月报)", text):
        return "report"
    if re.search(r"(查询|多少|最大|最小|水位|雨量|流量|涨水|超警|监测站|站点)", text):
        return "query"
    if re.search(r"(报告|快报|周报|月报|简报|通报)", text):
        return "report"
    return "query"


def call_nl2sql(nl_query: str) -> str:
    """
    调 NL2SQL：接收一条自然语言查询，返回 SQL 查询的执行结果（由下游服务决定格式）。
    - 出错时抛出异常，便于上层捕获。
    """
    print(f"[NL2SQL] 即将执行查询：{nl_query}")
    r = requests.post(
        NL2SQL_URL,
        json={"query": nl_query},
        headers={"Content-Type": "application/json"}
    )
    if not r.ok:
        # 将状态码与响应体截取拼入异常，便于排障
        raise RuntimeError(f"NL2SQL HTTP {r.status_code}. Body: {r.text}")
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"NL2SQL returned non-JSON: {r.text[:500]}")
    out = data.get("output")
    if out is None:
        raise RuntimeError(f"NL2SQL JSON has no 'output': {data}")
    return out

def build_report_user_input(user_goal: str, all_queries: List[str]) -> str:
    return (
        f"【报告目标】\n{user_goal}\n\n"
        f"【查询任务（按序）】\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(all_queries)) + "\n\n"
        f"【写作要求】\n请严格基于查询结果撰写报告，并尽量贴合所选模板的结构与语气。"
    )

# ===================== 图节点实现 =====================
def question_node(state: GraphState) -> GraphState:
    """
    主问题解析节点：
      1) 先在 graph 内做轻量意图判断；
      2) query 直接转成单条 NL 查询；
      3) report 则调用 template_planner 负责“找模板 + 拆模板”；
      4) 最终把 query1..N 统一整理进 plan。
    """
    new = dict(state)

    # 若 plan 已经存在（例如上游注入或前一步已完成），只补充快照后返回
    if new.get("plan"):
        if "all_queries_snapshot" not in new:
            new["all_queries_snapshot"] = list(new["plan"])
        return new

    meaning = _guess_intent(new["goal"])
    new["meaning"] = meaning
    queries: List[str] = []

    if meaning == "query":
        queries = [_resolve_relative_dates(f"请查询：{new['goal'].strip()}", base=datetime.now())]
        new["time"] = template_planner.extract_time_hint(new["goal"])
    elif meaning == "report":
        plan_obj = template_planner.plan_report(new["goal"])
        print("[DEBUG] template_planner:", plan_obj)
        if plan_obj.get("template_name") is not None:
            new["template_name"] = plan_obj.get("template_name")
        if plan_obj.get("time") is not None:
            new["time"] = plan_obj.get("time")
        raw_queries = plan_obj.get("queries") or []
        for item in raw_queries:
            if isinstance(item, str) and item.strip():
                queries.append(_resolve_relative_dates(item.strip(), base=datetime.now()))

    new["all_queries_snapshot"] = list(queries)
    new["plan"] = list(queries)
    return new

def pick_next_query_node(state: GraphState) -> GraphState:
    """
    轮询调度节点：
      - 从 plan 中按序取出一个 NL 查询，放入 current_query；
      - 若 plan 为空，则标记 done=True。
    """
    new = dict(state)
    new["iterations"] += 1
    if new["plan"]:
        new["current_query"] = new["plan"].pop(0)
    else:
        new["done"] = True
        new["current_query"] = None
    return new

def exec_nl2sql_node(state: GraphState) -> GraphState:
    """
    执行 NL2SQL 节点：
      - 读取 current_query，调用 NL2SQL；
      - 将查询与结果拼装成一个清晰的文本片段，追加到 results；
      - 清空 current_query。
    """
    new = dict(state)
    q = new.get("current_query")
    if not q:
        # 没有需要执行的查询，原样返回
        return new

    # 执行 NL2SQL 查询
    result = call_nl2sql(q)

    # 记录结果并清空当前查询
    new.setdefault("results", []).append({"query": q, "result": result})
    new["current_query"] = None
    return new


def _format_query_results(results: List[Dict[str, str]]) -> str:
    if not results:
        return "（NL2SQL 未产生任何结果）"

    blocks: List[str] = []
    for i, item in enumerate(results, start=1):
        q = (item.get("query") or "").strip()
        r = (item.get("result") or "").strip()
        blocks.append(
            f"## 查询 {i}\n"
            f"问题：{q or '（空）'}\n\n"
            f"结果：\n{r or '（无结果）'}"
        )
    return "\n\n".join(blocks)

def finalize_report_node(state: GraphState) -> GraphState:
    """
    收尾节点：
      - 若 meaning == "query"：不生成报告，直接汇总 NL2SQL 结果作为最终输出；
      - 其他情况（含 meaning == "report"）：调用报告服务生成 final_report。
      - 若已 done 且 final_report 尚未生成，则在此节点做最终处理。
    """
    new = dict(state)
    # 仅在“全部查询完成且还未生成 final_report”时进入处理
    if not new.get("done") or new.get("final_report"):
        return new

    meaning = (new.get("meaning") or "").lower()
    all_queries = new.get("all_queries_snapshot", [])
    all_results = new.get("results", [])

    if meaning == "query":
        # 只输出 NL2SQL 执行结果（不进入报告生成）
        new["final_report"] = _format_query_results(all_results)
        return new

    if meaning != "report":
        new["final_report"] = "暂不支持该类型请求。当前仅支持直接查询和生成报告。"
        return new

    # report 路径：基于模板与查询结果生成报告
    user_input = build_report_user_input(new["goal"], all_queries)
    report = report_writer.generate(
        user_input=user_input,
        external_query_results=all_results,
        template_name=new.get("template_name"),
        report_type=new.get("report_type"),
        time=new.get("time"),
        queries=all_queries,
    )
    new["final_report"] = report
    return new

# ===================== 构建 LangGraph =====================
def build_graph():
    """
    定义并编译 LangGraph：
      - 节点：question -> pick_next -> nl2sql -> finalize
      - 边：
          START -> question
          question -> pick_next
          pick_next -> (nl2sql | finalize)
          nl2sql -> pick_next
          finalize -> END
    """
    g = StateGraph(GraphState)

    # 注册节点
    g.add_node("analyze", question_node)
    g.add_node("pick_next", pick_next_query_node)
    g.add_node("nl2sql", exec_nl2sql_node)
    g.add_node("finalize", finalize_report_node)

    # 静态边
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "pick_next")

    # pick_next 已经决定了是否还有查询，因此在这里直接分流
    def route_after_pick_next(state: GraphState) -> Literal["nl2sql", "finalize"]:
        return "nl2sql" if state.get("current_query") else "finalize"

    g.add_conditional_edges("pick_next", route_after_pick_next, {
        "nl2sql": "nl2sql",
        "finalize": "finalize",
    })

    g.add_edge("nl2sql", "pick_next")

    g.add_edge("finalize", END)
    return g.compile()


# ===================== WebSocket 服务器 =====================
async def handle_websocket(websocket):
    """
    处理前端 WebSocket 连接 - 简化版本
    """
    print("前端已连接")

    try:
        async for message in websocket:
            # 前端直接发送用户输入文本，不需要 JSON 解析
            user_text = message.strip()

            if not user_text:
                await websocket.send("请输入有效的问题")
                continue

            print(f"收到用户输入: {user_text}")

            # 构建图应用
            app = build_graph()

            # 初始化状态
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
            }

            # 执行图流程
            final_state = app.invoke(init)

            # 只返回最终报告给前端
            final_report = final_state.get("final_report", "")
            await websocket.send(final_report)

    except websockets.exceptions.ConnectionClosed:
        print("前端连接已断开")
    except Exception as e:
        print(f"WebSocket 处理错误: {e}")
        await websocket.send(f"处理请求时出错: {str(e)}")


async def start_websocket_server():
    """
    启动 WebSocket 服务器
    """
    port = 8080  # 与前端对应的端口
    server = await websockets.serve(handle_websocket, "localhost", port)
    print(f"WebSocket 服务器启动在: ws://localhost:{port}")

    # 保持服务器运行
    await server.wait_closed()

# ===================== 命令行入口 =====================
# if __name__ == "__main__":
#     """
#     允许以脚本方式运行，便于本地快速验证：
#       - 输入：命令行提示输入“报告目标”（即 goal）
#       - 执行：按图流程依次运行
#       - 输出：打印“查询问题清单”与“最终输出”（标题随 meaning 的不同而变化）
#     """
#     app = build_graph()
#     user_text = input("请输入报告目标：").strip()
#
#     # 初始化状态
#     init: GraphState = {
#         "goal": user_text,
#         "plan": [],
#         "current_query": None,
#         "results": [],
#         "iterations": 0,
#         "done": False,
#         "final_report": "",
#         "all_queries_snapshot": [],
#         "meaning": None,
#     }
#
#     # 运行图
#     final_state = app.invoke(init)
#
#     # ====== 显式打印“查询问题”清单 ======
#     queries = final_state.get("all_queries_snapshot", [])
#     print("\n====== 显式打印“查询问题”清单 ======")
#     if queries:
#         for i, q in enumerate(queries, 1):
#             # 标注“可能被跳过”的控制型/范围型语句（仅做可视化提示）
#             tag = "[跳过]" if (q.startswith("时间范围") or q.startswith("查询时间段为")) else ""
#             print(f"{i}. {q} {tag}")
#     else:
#         print("（未生成查询问题；请检查 main_question 输出）")
#
#     # ====== 打印最终输出 ======
#     meaning = (final_state.get("meaning") or "").lower()
#     title = "最终报告" if meaning == "report" else "查询结果"
#     print(f"\n====== {title} ======\n")
#     print(final_state.get("final_report", "（未生成）"))
if __name__ == "__main__":
    # 默认以 WebSocket 模式运行
    print("启动 WebSocket 服务器模式...")

    try:
        asyncio.run(start_websocket_server())
    except KeyboardInterrupt:
        print("\nWebSocket 服务器已停止")
    except Exception as e:
        print(f"服务器启动失败: {e}")
