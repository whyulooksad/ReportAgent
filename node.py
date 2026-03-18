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
    errors: List[str]
    warnings: List[str]
    evidence_summary: List[Dict[str, Any]]
    outline: List[str]
    review_retry_counts: Dict[str, int]


def _fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _resolve_relative_dates(text: str, base: Optional[datetime] = None) -> str:
    if not text:
        return text
    base = base or datetime.now()
    today = base.date()
    yesterday = (base - timedelta(days=1)).date()
    tomorrow = (base + timedelta(days=1)).date()

    s_today = _fmt(datetime.combine(today, datetime.min.time()))
    s_yesterday = _fmt(datetime.combine(yesterday, datetime.min.time()))
    s_tomorrow = _fmt(datetime.combine(tomorrow, datetime.min.time()))

    out = text
    out = re.sub(r"今天(到|至)明天", f"{s_today}到{s_tomorrow}", out)
    out = out.replace("昨天", s_yesterday).replace("昨日", s_yesterday)
    out = out.replace("今天", s_today).replace("今日", s_today)
    out = out.replace("明天", s_tomorrow)
    return out


def _guess_intent(user_input: str) -> str:
    text = (user_input or "").strip()
    if not text:
        return "other"
    if re.search(r"(生成|撰写|写.{0,8}(报告|快报|周报|月报|简报|通报)|水情(报告|快报|周报|月报))", text):
        return "report"
    if re.search(r"(查询|多少|最大|最小|水位|雨量|流量|涨水|超警|监测站|站点)", text):
        return "query"
    if re.search(r"(报告|快报|周报|月报|简报|通报)", text):
        return "report"
    return "query"


def _call_nl2sql(nl_query: str) -> str:
    print(f"[NL2SQL] execute query: {nl_query}")
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
    return str(out)


def _build_report_user_input(user_goal: str, all_queries: List[str]) -> str:
    ordered_queries = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(all_queries))
    return (
        f"[报告目标]\n{user_goal}\n\n"
        f"[查询任务]\n{ordered_queries}\n\n"
        "[写作要求]\n请严格基于查询结果撰写报告，保持结构清晰，缺少证据的地方明确说明。"
    )


def _format_query_results(results: List[Dict[str, str]]) -> str:
    if not results:
        return "NL2SQL 未产生任何结果。"

    blocks: List[str] = []
    for i, item in enumerate(results, start=1):
        q = (item.get("query") or "").strip() or "（空）"
        r = (item.get("result") or "").strip() or "（无结果）"
        blocks.append(f"## 查询 {i}\n问题：{q}\n\n结果：\n{r}")
    return "\n\n".join(blocks)


def _looks_like_empty_result(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return True
    if normalized in {"[]", "{}", "null", "none", "nan"}:
        return True
    empty_markers = [
        "未查询到",
        "暂无数据",
        "没有数据",
        "无结果",
        "结果为空",
        "empty result",
        "no data",
        "no rows",
        "0 rows",
    ]
    return any(marker in normalized for marker in empty_markers)


def _looks_like_error_result(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    error_markers = [
        "traceback",
        "exception",
        "error",
        "failed",
        "超时",
        "失败",
        "错误",
        "异常",
        "http 5",
        "http 4",
    ]
    return any(marker in normalized for marker in error_markers)


def _summarize_result_text(text: str, max_len: int = 160) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return "结果为空"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len] + "..."


def _build_follow_up_query(query: str, reason: str) -> str:
    if reason == "error":
        return (
            f"请补查并核验：针对“{query}”，重新检查查询口径、时间范围和筛选条件；"
            "若仍失败，请明确说明失败原因。"
        )
    return (
        f"请补查并放宽条件：针对“{query}”，确认是否因时间范围、站点范围或过滤条件过严导致无结果；"
        "若确无数据，请明确说明无数据。"
    )


def _append_unique(items: List[str], message: str) -> None:
    if message and message not in items:
        items.append(message)


def _build_traceability_appendix(state: GraphState) -> str:
    lines: List[str] = []

    outline = state.get("outline") or []
    if outline:
        lines.append("## 报告提纲")
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(outline, start=1))

    evidence_items = state.get("evidence_summary") or []
    if evidence_items:
        lines.append("## 证据摘要")
        for item in evidence_items:
            idx = item.get("index")
            query = item.get("query") or "（空）"
            status = item.get("status") or "unknown"
            summary = item.get("summary") or ""
            lines.append(f"- [{idx}] {status} | {query}")
            if summary:
                lines.append(f"  摘要：{summary}")

    warnings = state.get("warnings") or []
    if warnings:
        lines.append("## 风险提示")
        lines.extend(f"- {item}" for item in warnings)

    errors = state.get("errors") or []
    if errors:
        lines.append("## 查询失败")
        lines.extend(f"- {item}" for item in errors)

    return "\n".join(lines).strip()


def intent_analysis_node(state: GraphState) -> GraphState:
    new = dict(state)
    new["meaning"] = _guess_intent(new.get("goal", ""))
    if new["meaning"] == "query":
        query = _resolve_relative_dates(f"请查询：{new['goal'].strip()}", base=datetime.now())
        new["plan"] = [query]
        new["all_queries_snapshot"] = [query]
        new["outline"] = [new["goal"].strip()]
        new["time"] = template_planner.extract_time_hint(new["goal"])
    elif new["meaning"] == "other":
        new["done"] = True
        new["outline"] = ["暂不支持的请求类型"]
    return new


def template_query_and_split_node(state: GraphState) -> GraphState:
    new = dict(state)
    if new.get("meaning") != "report":
        return new
    if new.get("plan"):
        if not new.get("all_queries_snapshot"):
            new["all_queries_snapshot"] = list(new["plan"])
        if not new.get("outline"):
            new["outline"] = list(new["plan"])
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
    new["outline"] = list(queries)
    return new


def scheduler_node(state: GraphState) -> GraphState:
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
    new = dict(state)
    q = new.get("current_query")
    if not q:
        return new
    result = _call_nl2sql(q)
    new.setdefault("results", []).append({"query": q, "result": result})
    new["current_query"] = None
    return new


def result_review_node(state: GraphState) -> GraphState:
    new = dict(state)
    results = new.get("results") or []
    if not results:
        return new

    latest = results[-1]
    query = (latest.get("query") or "").strip()
    result_text = latest.get("result") or ""
    retry_counts = dict(new.get("review_retry_counts") or {})

    status = "ok"
    if _looks_like_error_result(result_text):
        status = "error"
    elif _looks_like_empty_result(result_text):
        status = "empty"

    evidence_item = {
        "index": len(results),
        "query": query,
        "status": status,
        "summary": _summarize_result_text(result_text),
        "supports_conclusion": status == "ok",
    }
    new.setdefault("evidence_summary", []).append(evidence_item)

    retry_count = retry_counts.get(query, 0)
    if status in {"error", "empty"} and query and retry_count < 1:
        retry_counts[query] = retry_count + 1
        follow_up = _build_follow_up_query(query, status)
        new.setdefault("plan", []).insert(0, follow_up)
        new.setdefault("all_queries_snapshot", []).append(follow_up)
        new.setdefault("outline", []).append(f"补查：{query}")
        _append_unique(new.setdefault("warnings", []), f"查询“{query}”结果{status}，已加入一次补查。")
    elif status == "empty":
        _append_unique(new.setdefault("warnings", []), f"查询“{query}”未返回有效数据。")
    elif status == "error":
        _append_unique(new.setdefault("errors", []), f"查询“{query}”执行异常：{evidence_item['summary']}")

    new["review_retry_counts"] = retry_counts
    new["done"] = not bool(new.get("plan"))
    return new


def write_report_node(state: GraphState) -> GraphState:
    new = dict(state)
    if not new.get("done") or new.get("final_report"):
        return new

    meaning = (new.get("meaning") or "").lower()
    all_queries = new.get("all_queries_snapshot", [])
    all_results = new.get("results", [])

    if meaning == "query":
        body = _format_query_results(all_results)
        appendix = _build_traceability_appendix(new)
        new["final_report"] = body if not appendix else f"{body}\n\n{appendix}"
        return new

    if meaning != "report":
        new["final_report"] = "暂不支持该类型请求。当前仅支持直接查询和生成报告。"
        return new

    user_input = _build_report_user_input(new["goal"], all_queries)
    report_body = report_writer.generate(
        user_input=user_input,
        external_query_results=all_results,
        template_name=new.get("template_name"),
        report_type=new.get("report_type"),
        time=new.get("time"),
        queries=all_queries,
        outline=new.get("outline"),
        evidence_summary=new.get("evidence_summary"),
        warnings=new.get("warnings"),
        errors=new.get("errors"),
    )
    appendix = _build_traceability_appendix(new)
    new["final_report"] = report_body if not appendix else f"{report_body}\n\n{appendix}"
    return new


def route_after_scheduler(state: GraphState) -> Literal["nl2sql", "write_report"]:
    return "nl2sql" if state.get("current_query") else "write_report"


def route_after_result_review(state: GraphState) -> Literal["scheduler", "write_report"]:
    return "scheduler" if state.get("plan") else "write_report"
