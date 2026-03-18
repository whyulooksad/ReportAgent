# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, TypedDict

import requests

import report_writer
import template_planner


NL2SQL_URL = os.getenv("NL2SQL_URL", "http://localhost:8001/nl2sql")


class GraphState(TypedDict):
    """
    LangGraph 在节点之间传递的统一状态。

    字段约定：
    - goal: 用户原始输入
    - plan: 尚未执行的自然语言查询队列
    - current_query: 当前准备发送给 NL2SQL 的单条查询
    - results: 已完成查询的结果列表，每项为 {"query": "...", "result": "..."}
    - iterations: 调度轮次计数，便于排查流程
    - done: 是否已经没有剩余查询需要执行
    - final_report: 最终输出；report 场景下为报告正文，query 场景下为结果汇总
    - all_queries_snapshot: 完整查询列表快照，便于写报告时对齐结果
    - meaning: 意图分类结果，取值为 query / report / other
    - template_name: 报告场景下选中的模板名称
    - report_type: 预留字段，后续可用于区分周报、月报等类型
    - time: 从用户输入中提取到的时间提示
    """
    goal: str
    plan: List[str]
    current_query: Optional[str]
    results: List[Dict[str, str]]
    iterations: int
    done: bool
    final_report: str
    all_queries_snapshot: List[str]
    meaning: Optional[str]
    template_name: Optional[str]
    report_type: Optional[str]
    time: Optional[str]


def _fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _resolve_relative_dates(text: str, base: Optional[datetime] = None) -> str:
    if not text:
        return text
    base = base or datetime.now()
    d_today = base.date()
    d_yday = (base - timedelta(days=1)).date()
    d_tmr = (base + timedelta(days=1)).date()

    s_today = _fmt(datetime.combine(d_today, datetime.min.time()))
    s_yday = _fmt(datetime.combine(d_yday, datetime.min.time()))
    s_tmr = _fmt(datetime.combine(d_tmr, datetime.min.time()))

    out = text
    out = re.sub(r"今天(到|至)明天", f"{s_today}到{s_tmr}", out)
    out = out.replace("昨天", s_yday).replace("昨日", s_yday)
    out = out.replace("今天", s_today).replace("今日", s_today)
    out = out.replace("明天", s_tmr)
    return out


def _guess_intent(user_input: str) -> str:
    """
    对用户输入做轻量规则判断。

    当前只区分三类：
    - report: 生成某类报告、快报、周报等
    - query: 直接查询某个指标、站点或统计值
    - other: 空输入或无法识别的情况

    这里故意保持简单，避免把复杂“规划”逻辑塞回 graph。
    """
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


def _call_nl2sql(nl_query: str) -> str:
    print(f"[NL2SQL] 即将执行查询：{nl_query}")
    resp = requests.post(
        NL2SQL_URL,
        json={"query": nl_query},
        headers={"Content-Type": "application/json"},
    )
    if not resp.ok:
        raise RuntimeError(f"NL2SQL HTTP {resp.status_code}. Body: {resp.text}")
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"NL2SQL returned non-JSON: {resp.text[:500]}")
    out = data.get("output")
    if out is None:
        raise RuntimeError(f"NL2SQL JSON has no 'output': {data}")
    return out


def _build_report_user_input(user_goal: str, all_queries: List[str]) -> str:
    return (
        f"【报告目标】\n{user_goal}\n\n"
        f"【查询任务（按序）】\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(all_queries)) + "\n\n"
        f"【写作要求】\n请严格基于查询结果撰写报告，并尽量贴合所选模板的结构与语气。"
    )


def _format_query_results(results: List[Dict[str, str]]) -> str:
    if not results:
        return "（NL2SQL 未产生任何结果）"

    blocks: List[str] = []
    for i, item in enumerate(results, start=1):
        q = (item.get("query") or "").strip()
        r = (item.get("result") or "").strip()
        blocks.append(f"## 查询 {i}\n问题：{q or '（空）'}\n\n结果：\n{r or '（无结果）'}")
    return "\n\n".join(blocks)


def intent_analysis_node(state: GraphState) -> GraphState:
    """
    节点1：意图分析。

    职责：
    - 识别当前请求是 report、query 还是 other
    - 如果是 query，直接生成一条待执行查询并写入 plan
    - 如果是 other，直接标记 done=True，后续由写报告节点给出兜底输出

    输入关注：
    - goal

    输出更新：
    - meaning
    - plan
    - all_queries_snapshot
    - time
    - done
    """
    new = dict(state)
    new["meaning"] = _guess_intent(new.get("goal", ""))
    if new["meaning"] == "query":
        query = _resolve_relative_dates(f"请查询：{new['goal'].strip()}", base=datetime.now())
        new["plan"] = [query]
        new["all_queries_snapshot"] = [query]
        new["time"] = template_planner.extract_time_hint(new["goal"])
    elif new["meaning"] == "other":
        new["done"] = True
    return new


def template_query_and_split_node(state: GraphState) -> GraphState:
    """
    节点2：模板查询和分解。

    职责：
    - 仅在 meaning == "report" 时生效
    - 根据用户目标选择最匹配的模板
    - 将模板内容拆解为多条后续交给 NL2SQL 的自然语言查询
    - 将拆出的查询列表写入 plan，并保留全量快照

    输入关注：
    - goal
    - meaning

    输出更新：
    - template_name
    - time
    - plan
    - all_queries_snapshot

    说明：
    - query / other 场景下该节点直接透传，不做任何修改
    """
    new = dict(state)
    if new.get("meaning") != "report":
        return new
    if new.get("plan"):
        if not new.get("all_queries_snapshot"):
            new["all_queries_snapshot"] = list(new["plan"])
        return new

    plan_obj = template_planner.plan_report(new["goal"])
    print("[DEBUG] template_planner:", plan_obj)
    queries: List[str] = []
    for item in plan_obj.get("queries") or []:
        if isinstance(item, str) and item.strip():
            queries.append(_resolve_relative_dates(item.strip(), base=datetime.now()))

    new["template_name"] = plan_obj.get("template_name")
    new["time"] = plan_obj.get("time")
    new["plan"] = list(queries)
    new["all_queries_snapshot"] = list(queries)
    return new


def scheduler_node(state: GraphState) -> GraphState:
    """
    节点3：调度。

    职责：
    - 从 plan 队列头部取出一条查询，放到 current_query
    - 如果 plan 已空，则标记 done=True，流程转入写报告节点

    输入关注：
    - plan

    输出更新：
    - current_query
    - plan
    - done
    - iterations
    """
    new = dict(state)
    new["iterations"] += 1
    if new.get("plan"):
        new["current_query"] = new["plan"].pop(0)
        new["done"] = False
    else:
        new["current_query"] = None
        new["done"] = True
    return new


def nl2sql_node(state: GraphState) -> GraphState:
    """
    节点4：调用 NL2SQL。

    职责：
    - 将 current_query 发送给外部 NL2SQL 服务
    - 把返回结果追加到 results
    - 清空 current_query，等待下一轮调度

    输入关注：
    - current_query

    输出更新：
    - results
    - current_query
    """
    new = dict(state)
    q = new.get("current_query")
    if not q:
        return new
    result = _call_nl2sql(q)
    new.setdefault("results", []).append({"query": q, "result": result})
    new["current_query"] = None
    return new


def write_report_node(state: GraphState) -> GraphState:
    """
    节点5：写报告。

    职责：
    - 在所有查询执行完成后，根据意图决定最终输出
    - query 场景：直接汇总查询结果
    - report 场景：调用 report_writer 基于模板和查询结果生成报告
    - other 场景：返回兜底提示

    输入关注：
    - done
    - meaning
    - all_queries_snapshot
    - results
    - template_name
    - time

    输出更新：
    - final_report
    """
    new = dict(state)
    if not new.get("done") or new.get("final_report"):
        return new

    meaning = (new.get("meaning") or "").lower()
    all_queries = new.get("all_queries_snapshot", [])
    all_results = new.get("results", [])

    if meaning == "query":
        new["final_report"] = _format_query_results(all_results)
        return new

    if meaning != "report":
        new["final_report"] = "暂不支持该类型请求。当前仅支持直接查询和生成报告。"
        return new

    user_input = _build_report_user_input(new["goal"], all_queries)
    new["final_report"] = report_writer.generate(
        user_input=user_input,
        external_query_results=all_results,
        template_name=new.get("template_name"),
        report_type=new.get("report_type"),
        time=new.get("time"),
        queries=all_queries,
    )
    return new


def route_after_scheduler(state: GraphState) -> Literal["nl2sql", "write_report"]:
    """
    调度节点后的路由函数。

    - current_query 有值：说明本轮拿到了一条待执行查询，进入 nl2sql
    - current_query 为空：说明 plan 已耗尽，进入 write_report 收尾
    """
    return "nl2sql" if state.get("current_query") else "write_report"
