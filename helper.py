# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from openai import OpenAI

from state import GraphState

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))

def _get_llm_client(default_model: str = "qwen3-max") -> tuple[OpenAI, str]:
    """
    获取通用 LLM 客户端。

    约定：
    - Graph 内需要直接连 LLM 的节点，统一从这里取连接。
    - 模型名统一只读取环境变量 MODEL。
    """
    base_url = os.getenv("BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key = (
        os.getenv("DASHSCOPE_APIKEY"))
    if not api_key:
        raise RuntimeError("Missing DASHSCOPE_APIKEY (or DASHSCOPE_API_KEY / OPENAI_API_KEY / API_KEY).")

    model = os.getenv("MODEL") or default_model

    return OpenAI(api_key=api_key, base_url=base_url), model


def _fmt(d: datetime) -> str:
    """将日期格式化为 YYYY-MM-DD。"""
    return d.strftime("%Y-%m-%d")


def resolve_relative_dates(text: str, base: Optional[datetime] = None) -> str:
    """将少量常见相对日期替换为绝对日期。"""
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


def guess_intent_with_regex(goal: str) -> str:
    """节点 1 的本地回退规则：将用户请求粗分为 query / report / other。"""
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


def summarize_result_text(text: str, max_len: int = 160) -> str:
    """压缩结果文本，便于写入 evidence_summary / warnings / errors。"""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return "结果为空"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len] + "..."


def looks_like_error_result(text: str) -> bool:
    """节点 5 的本地回退规则：判断结果是否更像异常信息。"""
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


def looks_like_empty_result(text: str) -> bool:
    """节点 5 的本地回退规则：判断结果是否更像空结果。"""
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

def build_report_user_input(user_goal: str, all_queries: List[str]) -> str:
    """将报告目标和查询任务列表组装成写作输入。"""
    ordered_queries = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(all_queries))
    return (
        f"[报告目标]\n{user_goal}\n\n"
        f"[查询任务]\n{ordered_queries}\n\n"
        "[写作要求]\n请严格基于查询结果撰写报告，保持结构清晰，缺少证据的地方明确说明。"
    )


def format_query_results(results: List[Dict[str, str]]) -> str:
    """将 query 模式的结果列表格式化为可直接返回的文本。"""
    if not results:
        return "NL2SQL 未产生任何结果。"

    blocks: List[str] = []
    for i, item in enumerate(results, start=1):
        q = (item.get("query") or "").strip() or "（空）"
        r = (item.get("result") or "").strip() or "（无结果）"
        blocks.append(f"## 查询 {i}\n问题：{q}\n\n结果：\n{r}")
    return "\n\n".join(blocks)


def append_unique(items: List[str], message: str) -> None:
    """只在消息不存在时追加，避免重复错误或警告。"""
    if message and message not in items:
        items.append(message)


def build_traceability_appendix(state: GraphState) -> str:
    """生成可追溯附录。"""
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


def route_after_scheduler(state: GraphState) -> Literal["nl2sql", "write_report"]:
    """scheduler 之后：有 current_query 就去查，否则去写作。"""
    return "nl2sql" if state.get("current_query") else "write_report"


def route_after_result_review(state: GraphState) -> Literal["scheduler", "write_report"]:
    """result_review 之后：还有待查任务就回 scheduler，否则进入写作。"""
    return "scheduler" if state.get("plan") else "write_report"
