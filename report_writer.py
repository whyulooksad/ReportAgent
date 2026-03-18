# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from template_planner import TemplateStore


def _get_llm_client() -> tuple[OpenAI, str]:
    base_url = os.getenv("BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key = (
        os.getenv("DASHSCOPE_APIKEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("API_KEY")
        or ""
    )
    if not api_key:
        raise RuntimeError("Missing DASHSCOPE_APIKEY (or DASHSCOPE_API_KEY / OPENAI_API_KEY / API_KEY).")
    model = os.getenv("REPORT_MODEL") or os.getenv("MODEL") or "qwen3-max"
    return OpenAI(api_key=api_key, base_url=base_url), model


def _cap_text(s: Any, max_chars: int) -> str:
    t = "" if s is None else str(s)
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n...(truncated)"

def _strip_code_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```json\s*", "", t, flags=re.I).strip()
        t = re.sub(r"```$", "", t).strip()
    return t


def _normalize_query_results(external_query_results: List[Any], max_chars_per_result: int) -> List[Dict[str, str]]:
    packed: List[Dict[str, str]] = []
    for i, item in enumerate(external_query_results or [], start=1):
        if isinstance(item, dict):
            query = _cap_text(item.get("query"), 1000)
            result = _cap_text(item.get("result"), max_chars_per_result)
        else:
            query = ""
            result = _cap_text(item, max_chars_per_result)
        packed.append({"idx": str(i), "query": query, "result": result})
    return packed


def generate(
    user_input: str,
    external_query_results: List[Any],
    template_name: Optional[str] = None,
    report_type: Optional[str] = None,
    time: Optional[str] = None,
    queries: Optional[List[str]] = None,
    outline: Optional[List[str]] = None,
    evidence_summary: Optional[List[Dict[str, Any]]] = None,
    warnings: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
) -> str:
    llm, model = _get_llm_client()
    max_chars = int(os.getenv("MAX_CHARS_PER_RESULT") or "8000")

    store = TemplateStore()
    tpl = store.get_template(template_name) if template_name else None
    template_text = tpl.content if tpl and tpl.content else None

    qs = queries or []
    packed_results = _normalize_query_results(external_query_results or [], max_chars)

    system = """你是水文专家，负责撰写“水情报告/水情快报”。
硬性要求：
1) 必须严格基于 external_query_results 写作，不得编造数值；
2) 若缺数据，明确写“暂无相关数据/未查询到数据”，不要硬写；
3) 公文风格：正式、简洁、结构清晰，可分条；
4) 若提供模板文本，尽量贴合其标题与段落风格（但不要照抄示例中的具体数值）。
5) 若给出了查询问题列表，要把查询结果与对应问题对齐后再写，不要混淆口径。
只输出最终报告正文（不要输出 JSON，不要输出推理）。
"""

    payload: Dict[str, Any] = {
        "user_input": user_input,
        "template_name": template_name,
        "report_type": report_type,
        "time": time,
        "queries": qs,
        "outline": outline or [],
        "evidence_summary": evidence_summary or [],
        "warnings": warnings or [],
        "errors": errors or [],
        "external_query_results": packed_results,
        "template_text": template_text,
    }

    resp = llm.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()
