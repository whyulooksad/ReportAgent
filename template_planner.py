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

from helper import _get_llm_client, resolve_relative_dates

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))


DEFAULT_REGION = "四川省"
_REQUEST_PARSE_CACHE: Dict[str, Dict[str, Optional[str]]] = {}


@dataclass(frozen=True)
class TemplateEntry:
    template_name: str
    content: str
    source: str
    example_queries: List[str]


@dataclass(frozen=True)
class TemplateSection:
    title: str
    body: str


def _read_text_file(fp: str) -> str:
    return Path(fp).read_text(encoding="utf-8")


def _normalize_year_month(year: str, month: str) -> str:
    return f"{int(year):04d}-{int(month):02d}"


def _normalize_full_date(year: str, month: str, day: str) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _normalize_extracted_time(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    patterns = [
        (r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", _normalize_full_date),
        (r"(20\d{2})[-/.年](\d{1,2})月?", _normalize_year_month),
    ]
    for pattern, normalizer in patterns:
        match = re.search(pattern, text)
        if match:
            return normalizer(*match.groups())
    return text


def _normalize_report_type(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    if "日报" in text:
        return "日报"
    if "周报" in text:
        return "周报"
    if "月报" in text:
        return "月报"
    aliases = {
        "daily": "日报",
        "weekly": "周报",
        "monthly": "月报",
        "日": "日报",
        "周": "周报",
        "月": "月报",
    }
    return aliases.get(text.lower(), text)


def _parse_markdown_templates(text: str, source: str) -> List[TemplateEntry]:
    matches = list(re.finditer(r"(?m)^#\s+(.+?)\s*$", text))
    if not matches:
        return []

    entries: List[TemplateEntry] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        entries.append(
            TemplateEntry(
                template_name=match.group(1).strip(),
                content=text[start:end].strip(),
                source=source,
                example_queries=[],
            )
        )
    return entries


def extract_template_sections(template_text: str) -> List[TemplateSection]:
    text = (template_text or "").strip()
    if not text:
        return []

    markdown_sections = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if markdown_sections:
        sections: List[TemplateSection] = []
        for idx, match in enumerate(markdown_sections):
            start = match.end()
            end = markdown_sections[idx + 1].start() if idx + 1 < len(markdown_sections) else len(text)
            sections.append(TemplateSection(title=match.group(1).strip(), body=text[start:end].strip()))
        return sections

    numbered_sections = list(re.finditer(r"(?m)^([一二三四五六七八九十]+[、.．]\s*.+?)\s*$", text))
    if numbered_sections:
        sections = []
        for idx, match in enumerate(numbered_sections):
            start = match.end()
            end = numbered_sections[idx + 1].start() if idx + 1 < len(numbered_sections) else len(text)
            sections.append(TemplateSection(title=match.group(1).strip(), body=text[start:end].strip()))
        return sections

    return [TemplateSection(title="正文", body=text)]


class TemplateStore:
    def __init__(self, templates_dir: Optional[str] = None) -> None:
        default_dir = Path(__file__).resolve().parent / "templates"
        self.templates_dir = templates_dir or os.getenv("TEMPLATES_DIR") or str(default_dir)

    def list_templates(self) -> List[TemplateEntry]:
        if not self.templates_dir or not os.path.isdir(self.templates_dir):
            return []

        entries: List[TemplateEntry] = []
        for pattern in ("*.md", "*.txt"):
            for fp in sorted(glob.glob(os.path.join(self.templates_dir, pattern))):
                try:
                    text = _read_text_file(fp)
                except Exception:
                    continue

                if fp.lower().endswith(".md"):
                    parsed = _parse_markdown_templates(text, source=f"local:{fp}")
                    if parsed:
                        entries.extend(parsed)
                        continue

                entries.append(
                    TemplateEntry(
                        template_name=os.path.splitext(os.path.basename(fp))[0],
                        content=text,
                        source=f"local:{fp}",
                        example_queries=[],
                    )
                )
        return entries

    def get_template(self, template_name: Optional[str]) -> Optional[TemplateEntry]:
        target = (template_name or "").strip()
        if not target:
            return None
        for item in self.list_templates():
            if item.template_name == target:
                return item
        return None


def extract_request_context(user_input: str) -> Dict[str, Optional[str]]:
    text = (user_input or "").strip()
    if not text:
        return {"normalized_goal": "", "time": None, "region": None, "report_type": None}

    cached = _REQUEST_PARSE_CACHE.get(text)
    if cached is not None:
        return dict(cached)

    normalized_goal = resolve_relative_dates(text)
    result: Dict[str, Optional[str]] = {
        "normalized_goal": normalized_goal,
        "time": None,
        "region": None,
        "report_type": None,
    }

    llm, model = _get_llm_client(default_model="qwen3-max")
    system = (
        "你是报告请求信息提取器，负责从用户请求中提取报告类型、时间和地区。\n"
        "请只输出一个 JSON 对象，不要输出任何解释、注释或多余文本。\n"
        "输出字段要求：\n"
        "- report_type: 只能是 日报、周报、月报 或 null。\n"
        "- time: 优先提取为 YYYY-MM-DD 或 YYYY-MM；如果无法明确提取，返回 null。\n"
        "- region: 只返回用户明确提到的地区名称；如果用户没有明确提地区，返回 null。\n"
        "注意：\n"
        "- 不要猜测用户没说出的地区。\n"
        "- “简报”“快报”等不强制映射成 日报/周报/月报，除非用户表达非常明确。\n"
        "- 如果文本里有多个时间，优先返回最能代表整份报告统计范围的那个时间。"
    )
    payload = {
        "task": "extract_report_request_context",
        "fewshots": [
            {
                "normalized_input": "生成2026-03-22四川省水情日报",
                "output": {"report_type": "日报", "time": "2026-03-22", "region": "四川省"},
            },
            {
                "normalized_input": "帮我写2026年3月成都市雨情月报",
                "output": {"report_type": "月报", "time": "2026-03", "region": "四川省成都市"},
            },
            {
                "normalized_input": "生成2026-03-22的日报",
                "output": {"report_type": "日报", "time": "2026-03-22", "region": None},
            },
        ],
        "normalized_input": normalized_goal,
    }
    resp = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    obj = json.loads((resp.choices[0].message.content or "").strip())
    result["time"] = _normalize_extracted_time(obj.get("time"))
    result["region"] = str(obj.get("region")).strip() if obj.get("region") else None
    result["report_type"] = _normalize_report_type(obj.get("report_type"))

    _REQUEST_PARSE_CACHE[text] = dict(result)
    return result


def _select_template(
    llm: OpenAI,
    model: str,
    user_input: str,
    templates: List[TemplateEntry],
    report_type: Optional[str],
) -> Optional[str]:
    if not templates:
        return None

    if report_type:
        for item in templates:
            if item.template_name == report_type:
                return item.template_name

    candidates = []
    max_candidates = int(os.getenv("MAX_TEMPLATE_CANDIDATES") or "30")
    for item in templates[:max_candidates]:
        preview = (item.content or "").strip().replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:200] + "..."
        candidates.append({"template_name": item.template_name, "preview": preview})

    system = (
        "你是报告模板选择器，负责从候选模板中选出最适合当前报告需求的一份模板。\n"
        "判断时优先考虑：报告类型是否匹配、模板章节是否符合用户需求、模板名称和模板内容是否与请求语义一致。\n"
        "请只输出一个 JSON 对象，例如 {\"template_name\":\"月报\"}，不要输出解释。\n"
        "如果多个模板都接近，优先选择报告类型一致、内容更通用、覆盖面更完整的模板。"
    )
    payload = {
        "user_input": user_input,
        "report_type": report_type,
        "candidates": candidates,
    }
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


def _clean_section_name(title: str) -> str:
    cleaned = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", (title or "").strip())
    if not cleaned:
        return "正文"
    for item in ["雨情", "水情", "汛情", "旱情", "工情", "水质"]:
        if item in cleaned:
            return item
    return cleaned


def _dedupe_keep_order(items: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        value = (item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _load_schema_excerpt(max_chars: int = 12000) -> str:
    schema_file = Path(__file__).resolve().parent / "NL2SQL" / "schema_cache" / "schema.json"
    if not schema_file.exists():
        return ""
    try:
        data = json.loads(schema_file.read_text(encoding="utf-8"))
    except Exception:
        return ""
    schema_text = str(data.get("schema_data") or "").strip()
    if not schema_text:
        return ""
    if len(schema_text) <= max_chars:
        return schema_text
    return schema_text[:max_chars] + "\n...[schema truncated]..."


def _build_query_tasks_from_outline(
    outline: List[str],
    time_value: Optional[str],
    region_value: Optional[str],
) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for idx, section_name in enumerate(outline, start=1):
        name = (section_name or "").strip() or f"section_{idx}"
        tasks.append(
            {
                "task_id": f"sec{idx}_q1",
                "section_title": name,
                "goal": f"支撑{name}部分写作所需的数据查询",
                "must_include": [item for item in [time_value, region_value, name] if item],
                "comparison_target": None,
                "priority": idx,
            }
        )
    return tasks


def _generate_queries_with_schema(
    user_input: str,
    template: Optional[TemplateEntry],
    report_type: Optional[str],
    time_value: Optional[str],
    region_value: str,
) -> Dict[str, Any]:
    template_text = template.content if template else ""
    sections = extract_template_sections(template_text)
    outline = [_clean_section_name(section.title) for section in sections] or ["总体情况"]
    query_tasks = _build_query_tasks_from_outline(outline, time_value, region_value)
    schema_excerpt = _load_schema_excerpt()

    if not template_text or not schema_excerpt:
        return {
            "time": time_value,
            "region": region_value,
            "report_type": report_type,
            "outline": outline,
            "query_tasks": query_tasks,
            "queries": [],
            "warnings": ["模板或 schema 不完整，无法生成查询计划。"],
        }

    system = (
        "你是报告查询规划器，负责把报告写作需求转换成一组可由后续数据查询模块执行的自然语言数据查询请求。\n"
        "后续模块会把这些自然语言查询转换成 SQL 并执行，因此你的 queries 必须是明确、完整、可独立执行的数据查询语句。\n"
        "你的输入包含：用户需求、报告类型、时间、地区、报告模板正文、模板章节提纲、数据库 schema 摘要。\n"
        "你的任务是：\n"
        "1. 先根据模板正文和模板章节，理解这份报告通常需要覆盖哪些核心部分。\n"
        "2. 再结合 schema 摘要，判断数据库里大概率可查询的对象、指标、区域和时间维度。\n"
        "3. 为每个重要章节规划 1 到 2 条自然语言查询，用于支撑后续写作。\n"
        "4. 查询必须围绕用户要求的时间和地区展开，不能遗漏时间或地区。\n"
        "5. 不要输出 SQL，不要输出报告正文，不要编造 schema 中明显不存在的表、字段、指标、站点或维度。\n"
        "6. 避免生成重复或高度相似的查询。\n"
        "\n"
        "输出要求：\n"
        "只输出一个 JSON 对象，禁止输出任何额外解释。\n"
        "JSON 必须包含以下字段：\n"
        "- outline: 字符串数组，表示最终采用的报告章节提纲。\n"
        "- query_tasks: 数组，每项是对象，包含 task_id、section_title、goal、must_include、comparison_target、priority。\n"
        "- queries: 字符串数组，表示最终生成的自然语言查询语句。\n"
        "\n"
        "额外要求：\n"
        "- user_input 的业务需求优先级最高。\n"
        "- template_outline 是章节骨架，template_text 用于理解每章想写什么。\n"
        "- schema_excerpt 用于约束“哪些内容可能可查”，而不是让你复述 schema。\n"
        "- 如果某个模板章节缺乏足够 schema 支撑，可以弱化该章节，不要硬编数据项。"
    )
    payload = {
        "user_input": user_input,
        "report_type": report_type,
        "time": time_value,
        "region": region_value,
        "template_name": template.template_name if template else None,
        "template_text": template_text,
        "template_outline": outline,
        "schema_excerpt": schema_excerpt,
    }

    llm, model = _get_llm_client(default_model="qwen3-max")
    resp = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    result = json.loads(resp.choices[0].message.content or "{}")

    queries = _dedupe_keep_order([item for item in (result.get("queries") or []) if isinstance(item, str)])
    llm_tasks = result.get("query_tasks") if isinstance(result.get("query_tasks"), list) else []
    normalized_tasks: List[Dict[str, Any]] = []
    for idx, item in enumerate(llm_tasks, start=1):
        if not isinstance(item, dict):
            continue
        normalized_tasks.append(
            {
                "task_id": str(item.get("task_id") or f"sec{idx}_q1"),
                "section_title": str(item.get("section_title") or outline[min(idx - 1, len(outline) - 1)]),
                "goal": str(item.get("goal") or "报告查询任务"),
                "must_include": [str(v) for v in (item.get("must_include") or []) if str(v).strip()],
                "comparison_target": item.get("comparison_target"),
                "priority": int(item.get("priority") or idx),
            }
        )

    return {
        "time": time_value,
        "region": region_value,
        "report_type": report_type,
        "outline": result.get("outline") or outline,
        "query_tasks": normalized_tasks or query_tasks,
        "queries": queries,
        "warnings": [] if queries else ["LLM 未生成有效查询。"],
    }


def plan_template_queries(
    goal: str,
    report_type: Optional[str] = None,
    time: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    text = (goal or "").strip()
    if not text:
        return {
            "template_name": None,
            "template_text": None,
            "time": time,
            "region": region,
            "report_type": report_type,
            "outline": [],
            "query_tasks": [],
            "queries": [],
            "warnings": [],
        }

    context = extract_request_context(text)
    resolved_report_type = report_type or context.get("report_type")
    resolved_time = time or context.get("time")
    resolved_region = region or context.get("region") or DEFAULT_REGION

    template = None
    warnings: List[str] = []
    store = TemplateStore()
    templates = store.list_templates()
    if templates:
        llm, model = _get_llm_client(default_model="qwen3-max")
        chosen_name = _select_template(llm, model, text, templates, resolved_report_type)
        template = store.get_template(chosen_name) if chosen_name else None
    else:
        warnings.append("未找到任何可用模板。")

    planned = _generate_queries_with_schema(
        user_input=text,
        template=template,
        report_type=resolved_report_type or (template.template_name if template else None),
        time_value=resolved_time,
        region_value=resolved_region,
    )
    for item in planned.get("warnings") or []:
        if item not in warnings:
            warnings.append(item)

    return {
        "template_name": template.template_name if template else None,
        "template_text": template.content if template else None,
        "time": planned.get("time"),
        "region": planned.get("region"),
        "report_type": planned.get("report_type"),
        "outline": list(planned.get("outline") or []),
        "query_tasks": list(planned.get("query_tasks") or []),
        "queries": list(planned.get("queries") or []),
        "warnings": warnings,
    }
