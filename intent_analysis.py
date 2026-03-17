# -*- coding: utf-8 -*-
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI


def _get_llm_client() -> tuple[OpenAI, str]:
    base_url = os.getenv("BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key = os.getenv("DASHSCOPE_APIKEY")
    if not api_key:
        raise RuntimeError("Missing DASHSCOPE_APIKEY")
    model = os.getenv("QUESTION_MODEL") or "qwen3-max"
    return OpenAI(api_key=api_key, base_url=base_url), model


def _get_schema_text() -> str:
    try:
        from NL2SQL.schema_cache import get_schema  # type: ignore

        return get_schema()
    except Exception:
        return ""


def _extract_time_hint(user_input: str) -> Optional[str]:
    t = (user_input or "").strip()
    if not t:
        return None
    m = re.search(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", t)
    if not m:
        return None
    return m.group(1).replace("/", "-").replace(".", "-")


def _guess_intent(user_input: str) -> str:
    t = (user_input or "").strip()
    if not t:
        return "other"
    if re.search(r"(生成|撰写|写|出).{0,8}(报告|快报|周报|月报|简报|通报)|水情(报告|快报|周报|月报)", t):
        return "report"
    if re.search(r"(查询|多少|最大|最小|水位|雨量|流量|涨水|超警|监测站|站点)", t):
        return "query"
    # 含“报告/快报”等但没动词，也按 report 兜底
    if re.search(r"(报告|快报|周报|月报|简报|通报)", t):
        return "report"
    return "query"


@dataclass(frozen=True)
class TemplateEntry:
    template_name: str
    content: str
    source: str  # local:<path> | mysql
    example_queries: List[str]


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s)
    return s.strip("_") or "template"


class TemplateStore:
    def __init__(self, templates_dir: Optional[str] = None) -> None:
        self.templates_dir = templates_dir or (os.getenv("TEMPLATES_DIR") or os.path.join(os.getcwd(), "templates"))

    def _list_local(self) -> List[TemplateEntry]:
        d = self.templates_dir
        if not d or not os.path.isdir(d):
            return []
        out: List[TemplateEntry] = []
        for fp in sorted(glob.glob(os.path.join(d, "*.txt"))):
            try:
                text = open(fp, "r", encoding="utf-8").read()
            except Exception:
                continue
            name = os.path.splitext(os.path.basename(fp))[0]
            out.append(TemplateEntry(template_name=name, content=text, source=f"local:{fp}", example_queries=[]))
        return out

    def _list_mysql(self) -> List[TemplateEntry]:
        # 可选：若环境装了 PyMySQL 且配置了 DB_*，就从 templet/templetquestion 拉模板与示例问题
        try:
            import pymysql  # type: ignore
        except Exception:
            return []

        host = os.getenv("DB_HOST")
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASSWORD")
        db = os.getenv("DB_NAME")
        port = int(os.getenv("DB_PORT") or "3306")
        if not (host and user and password and db):
            return []

        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.templetname, t.content, q.questioncontent
                    FROM templet t
                    JOIN templetquestion q ON t.templetid = q.templetid
                    """
                )
                rows = cur.fetchall() or []
        finally:
            conn.close()

        by_name: dict[str, dict] = {}
        for r in rows:
            name = (r.get("templetname") or "").strip()
            if not name:
                continue
            item = by_name.setdefault(name, {"content": r.get("content") or "", "queries": []})
            q = r.get("questioncontent") or ""
            if q:
                item["queries"].append(str(q))

        out: List[TemplateEntry] = []
        for name, item in by_name.items():
            out.append(
                TemplateEntry(
                    template_name=_safe_name(name),
                    content=item.get("content") or "",
                    source="mysql",
                    example_queries=item.get("queries") or [],
                )
            )
        return out

    def list_templates(self) -> List[TemplateEntry]:
        local = self._list_local()
        mysql = self._list_mysql()
        # 同名时 local 优先
        seen = set()
        merged: List[TemplateEntry] = []
        for e in local + mysql:
            if e.template_name in seen:
                continue
            seen.add(e.template_name)
            merged.append(e)
        return merged

    def get_template(self, template_name: Optional[str]) -> Optional[TemplateEntry]:
        name = (template_name or "").strip()
        if not name:
            return None
        for t in self.list_templates():
            if t.template_name == name:
                return t
        return None


def _select_template(llm: OpenAI, model: str, user_input: str, templates: List[TemplateEntry]) -> Optional[str]:
    if not templates:
        return None
    max_candidates = int(os.getenv("MAX_TEMPLATE_CANDIDATES") or "30")
    cand = []
    for t in templates[:max_candidates]:
        preview = (t.content or "").strip().replace("\n", " ")
        if len(preview) > 160:
            preview = preview[:160] + "..."
        cand.append({"template_name": t.template_name, "preview": preview})

    system = """你是模板选择器。只输出 JSON。
从候选中选择最适合用户需求的 template_name；若无法确定，返回 null。
输出：{"template_name": "..."} 或 {"template_name": null}
"""
    resp = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"user_input": user_input, "candidates": cand}, ensure_ascii=False)},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    obj = json.loads(resp.choices[0].message.content or "{}")
    name = obj.get("template_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _generate_queries(llm: OpenAI, model: str, user_input: str, template: Optional[TemplateEntry], time_hint: Optional[str]) -> List[str]:
    schema = _get_schema_text()
    system = """你是“报告->查询任务”生成器。只输出 JSON 数组（禁止输出其它文本）。

目标：生成一组可直接交给 NL2SQL 的自然语言查询句子。
要求：
1) 每条查询必须尽量明确：时间范围、区域/对象、指标与统计口径；
2) 每条查询尽量以“请查询”开头；
3) 不要写 SQL，不要出现表名字段名；
4) 若用户未给出时间范围，第一条查询用于确定默认时间范围（例如今天/最近24小时/最近一周），后续查询复用同一时间范围表述；
5) 一般输出 4~10 条。
"""
    payload = {
        "user_input": user_input,
        "time_hint": time_hint,
        "template_name": template.template_name if template else None,
        "template_text": template.content if template else None,
        "template_example_queries": (template.example_queries[:10] if template else []),
        "db_schema": schema,
    }
    resp = llm.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        temperature=0.2,
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```json\s*", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    arr = json.loads(text)
    if not isinstance(arr, list):
        return []
    out = []
    for x in arr:
        s = ("" if x is None else str(x)).strip()
        if s:
            out.append(s)
    return out


def plan(user_input: str) -> Dict[str, Any]:
    """
    返回结构兼容 multi_agent_graph：
      - meaning: query|report|other
      - query1..queryN: 待执行的自然语言查询
      - template_name/time/report_type: 可选元信息（供 report 端）
    """
    text = (user_input or "").strip()
    if not text:
        return {"meaning": "other"}

    meaning = _guess_intent(text)
    time_hint = _extract_time_hint(text)

    if meaning == "query":
        return {"meaning": "query", "query1": f"请查询：{text}", "time": time_hint}
    if meaning != "report":
        return {"meaning": "other"}

    llm, model = _get_llm_client()
    store = TemplateStore()
    templates = store.list_templates()
    chosen = _select_template(llm, model, text, templates)
    tpl = store.get_template(chosen) if chosen else None
    if not tpl and templates:
        tpl = templates[0]

    queries = _generate_queries(llm, model, text, tpl, time_hint)
    if not queries:
        queries = [
            f"请查询：{text}（涉及的关键水文指标与统计口径）",
            f"请查询：{text}（极值、超警/涨水情况与站点/地区分布）",
        ]

    obj: Dict[str, Any] = {"meaning": "report", "template_name": tpl.template_name if tpl else None, "time": time_hint}
    for i, q in enumerate(queries, start=1):
        obj[f"query{i}"] = q
    return obj

