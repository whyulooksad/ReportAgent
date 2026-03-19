# -*- coding: utf-8 -*-
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from helper import _get_llm_client

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))
def extract_time_hint(user_input: str) -> Optional[str]:
    text = (user_input or "").strip()
    if not text:
        return None
    match = re.search(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", text)
    if not match:
        return None
    return match.group(1).replace("/", "-").replace(".", "-")


@dataclass(frozen=True)
class TemplateEntry:
    template_name: str
    content: str
    source: str
    example_queries: List[str]


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s)
    return s.strip("_") or "template"


class TemplateStore:
    def __init__(self, templates_dir: Optional[str] = None) -> None:
        self.templates_dir = templates_dir or (os.getenv("TEMPLATES_DIR") or os.path.join(os.getcwd(), "templates"))

    def _list_local(self) -> List[TemplateEntry]:
        if not self.templates_dir or not os.path.isdir(self.templates_dir):
            return []
        entries: List[TemplateEntry] = []
        for fp in sorted(glob.glob(os.path.join(self.templates_dir, "*.txt"))):
            try:
                text = open(fp, "r", encoding="utf-8").read()
            except Exception:
                continue
            name = os.path.splitext(os.path.basename(fp))[0]
            entries.append(TemplateEntry(template_name=name, content=text, source=f"local:{fp}", example_queries=[]))
        return entries

    def _list_mysql(self) -> List[TemplateEntry]:
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

        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            name = (row.get("templetname") or "").strip()
            if not name:
                continue
            item = grouped.setdefault(name, {"content": row.get("content") or "", "queries": []})
            question = row.get("questioncontent") or ""
            if question:
                item["queries"].append(str(question))

        entries: List[TemplateEntry] = []
        for name, item in grouped.items():
            entries.append(
                TemplateEntry(
                    template_name=_safe_name(name),
                    content=item.get("content") or "",
                    source="mysql",
                    example_queries=item.get("queries") or [],
                )
            )
        return entries

    def list_templates(self) -> List[TemplateEntry]:
        local = self._list_local()
        mysql = self._list_mysql()
        seen = set()
        merged: List[TemplateEntry] = []
        for entry in local + mysql:
            if entry.template_name in seen:
                continue
            seen.add(entry.template_name)
            merged.append(entry)
        return merged

    def get_template(self, template_name: Optional[str]) -> Optional[TemplateEntry]:
        name = (template_name or "").strip()
        if not name:
            return None
        for entry in self.list_templates():
            if entry.template_name == name:
                return entry
        return None


def _select_template(llm: OpenAI, model: str, user_input: str, templates: List[TemplateEntry]) -> Optional[str]:
    if not templates:
        return None

    max_candidates = int(os.getenv("MAX_TEMPLATE_CANDIDATES") or "30")
    candidates = []
    for template in templates[:max_candidates]:
        preview = (template.content or "").strip().replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:200] + "..."
        candidates.append({"template_name": template.template_name, "preview": preview})

    system = """你是模板选择器。只输出 JSON。
请从候选模板中选出最适合当前报告需求的 template_name。
如果无法判断，返回 {"template_name": null}。
"""
    payload = {"user_input": user_input, "candidates": candidates}
    resp = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    obj = json.loads(resp.choices[0].message.content or "{}")
    name = obj.get("template_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _split_template_to_queries(
    llm: OpenAI,
    model: str,
    user_input: str,
    template: Optional[TemplateEntry],
    time_hint: Optional[str],
) -> List[str]:
    if not template or not (template.content or "").strip():
        return []

    system = """你是“报告模板拆解器”。只输出 JSON 数组，不要输出其它文本。

任务：根据用户的报告需求和模板内容，把模板拆成一组后续可交给 NL2SQL 的自然语言查询任务。
要求：
1) 每条任务都要尽量明确查询对象、指标、时间范围和统计口径；
2) 每条任务尽量以“请查询”开头；
3) 不要写 SQL，不要出现表名字段名；
4) 只需要输出查询任务列表，不要解释；
5) 一般输出 4 到 10 条；
6) 如果模板里有明显的段落结构，应尽量覆盖这些段落对应的数据需求。
"""
    payload = {
        "user_input": user_input,
        "time_hint": time_hint,
        "template_name": template.template_name,
        "template_text": template.content,
        "template_example_queries": template.example_queries[:10],
    }
    resp = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.2,
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```json\s*", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    arr = json.loads(text)
    if not isinstance(arr, list):
        return []

    queries: List[str] = []
    for item in arr:
        query = ("" if item is None else str(item)).strip()
        if query:
            queries.append(query)
    return queries


def plan_report(user_input: str) -> Dict[str, Any]:
    text = (user_input or "").strip()
    if not text:
        return {"template_name": None, "time": None, "queries": []}

    time_hint = extract_time_hint(text)
    llm, model = _get_llm_client(default_model="qwen3-max")
    store = TemplateStore()
    templates = store.list_templates()
    chosen_name = _select_template(llm, model, text, templates)
    template = store.get_template(chosen_name) if chosen_name else None
    if not template and templates:
        template = templates[0]

    queries = _split_template_to_queries(llm, model, text, template, time_hint)
    if not queries and template and template.example_queries:
        queries = [str(q).strip() for q in template.example_queries if str(q).strip()]
    if not queries:
        queries = [
            f"请查询：{text}涉及的关键水文指标与统计口径",
            f"请查询：{text}涉及的极值、超警情况以及站点或区域分布",
        ]

    return {
        "template_name": template.template_name if template else None,
        "template_text": template.content if template else None,
        "time": time_hint,
        "queries": queries,
    }
