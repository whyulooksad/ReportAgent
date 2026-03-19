# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import requests
import report_writer
import template_planner
from helper import (
    _get_llm_client,
    append_unique,
    build_report_user_input,
    build_traceability_appendix,
    format_query_results,
    guess_intent_with_regex,
    looks_like_empty_result,
    looks_like_error_result,
    resolve_relative_dates,
    summarize_result_text,
)
from state import GraphState


def intent_analysis_node(state: GraphState) -> GraphState:
    """
    节点 1：意图分析。

    目标：
    - 判断当前请求属于 query / report / other 中的哪一类。

    实现策略：
    - 主路径：直接在节点内部调用 LLM 做意图判断。
    - 兜底路径：如果 LLM 连接失败、超时、返回异常，回退到本地正则规则。

    输出约束：
    - 最终只允许写回 query / report / other 三种 meaning。
    - 如果是 query，会直接生成一条待执行查询任务。
    - 如果是 other，会提前标记 done，由写作节点兜底返回。
    """
    new = dict(state)
    goal = (new.get("goal") or "").strip()
    meaning = "other"

    if goal:
        try:
            llm, model = _get_llm_client()
            system = (
                "你是一个意图分类器。"
                "请把用户请求分类为 query、report、other 三类之一。"
                "只输出 JSON，例如 {\"intent\": \"query\"}。"
                "规则：\n"
                "- report: 用户明确要求生成、撰写、输出报告、快报、周报、月报、简报等。\n"
                "- query: 用户是在查询某个指标、站点、时间段数据或统计结果。\n"
                "- other: 空输入、闲聊、或既不是报告也不是数据查询。\n"
            )
            payload = {
                "task": "classify_intent",
                "labels": ["query", "report", "other"],
                "fewshots": [
                    {"input": "生成今天的水情日报", "intent": "report"},
                    {"input": "帮我写一份本周雨情周报", "intent": "report"},
                    {"input": "查询昨天各站点最大雨量", "intent": "query"},
                    {"input": "三峡站今天最高水位是多少", "intent": "query"},
                    {"input": "你好", "intent": "other"},
                ],
                "user_input": goal,
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
            content = (resp.choices[0].message.content or "").strip()
            obj = json.loads(content)
            meaning = str(obj.get("intent") or "").strip().lower()
            if meaning not in {"query", "report", "other"}:
                raise RuntimeError(f"Invalid intent from LLM: {meaning}")
        except Exception as exc:
            print(f"[intent_analysis] fallback to regex due to LLM failure: {exc}")
            meaning = guess_intent_with_regex(goal)

    new["meaning"] = meaning

    if meaning == "query":
        query = resolve_relative_dates(f"请查询：{goal}", base=datetime.now())
        new["plan"] = [query]
        new["all_queries_snapshot"] = [query]
        new["outline"] = [goal]
        new["time"] = template_planner.extract_time_hint(goal)
    elif meaning == "other":
        new["done"] = True
        new["outline"] = ["暂不支持的请求类型"]

    return new


def template_query_and_split_node(state: GraphState) -> GraphState:
    """
    节点 2：模板选择和查询拆解。

    目标：
    - 仅在 report 场景下，把“写报告”转换成“先查哪些数据”。

    实现策略：
    - 如果当前不是 report，直接透传，不做修改。
    - 如果上游已经生成过 plan，就不重复规划，只补齐快照字段。
    - 如果还没有 plan，则调用 template_planner.plan_report：
      1. 选模板
      2. 从模板中拆出多条自然语言查询任务
      3. 对拆出的查询做相对时间归一化

    写回字段：
    - template_name: 选中的模板名称
    - time: 从规划阶段提取出的时间提示
    - plan: 后续要交给 NL2SQL 执行的查询队列
    - all_queries_snapshot: 查询任务全量快照
    - outline: 初始报告提纲，当前直接复用查询任务列表
    """
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

    queries: list[str] = []
    for item in plan_obj.get("queries") or []:
        if isinstance(item, str) and item.strip():
            queries.append(resolve_relative_dates(item.strip(), base=datetime.now()))

    new["template_name"] = plan_obj.get("template_name")
    new["time"] = plan_obj.get("time")
    new["plan"] = list(queries)
    new["all_queries_snapshot"] = list(queries)
    new["outline"] = list(queries)
    return new


def scheduler_node(state: GraphState) -> GraphState:
    """
    节点 3：调度器。

    目标：
    - 从 plan 中逐条取出查询，控制图按“单条查询 -> 单次执行”的节奏推进。

    实现策略：
    - 每次进入节点都把 iterations 加一，便于观察总轮次。
    - 如果 plan 非空：
      - 取队首一条写入 current_query
      - done=False
    - 如果 plan 为空：
      - current_query=None
      - done=True，后续可进入写作阶段

    这个节点本身不做查询，也不判断结果好坏，只负责发下一条任务。
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
    节点 4：执行 NL2SQL。

    目标：
    - 把当前的 current_query 交给现有 NL2SQL 服务执行。

    实现策略：
    - 如果 current_query 为空，直接透传。
    - 如果 current_query 有值：
      - 直接调用现有 NL2SQL 服务
      - 将结果以 {query, result} 的形式追加到 results
      - 清空 current_query

    这个节点只负责执行，不负责判断结果是否为空、异常或是否需要补查。
    这些工作交给节点 5 处理。
    """
    new = dict(state)
    q = new.get("current_query")
    if not q:
        return new

    nl2sql_url = os.getenv("NL2SQL_URL", "http://localhost:8001/nl2sql")
    print(f"[NL2SQL] execute query: {q}")
    resp = requests.post(
        nl2sql_url,
        json={"query": q},
        headers={"Content-Type": "application/json"},
    )
    if not resp.ok:
        raise RuntimeError(f"NL2SQL HTTP {resp.status_code}. Body: {resp.text}")

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"NL2SQL returned non-JSON: {resp.text[:500]}")

    result = data.get("output")
    if result is None:
        raise RuntimeError(f"NL2SQL JSON has no 'output': {data}")

    new.setdefault("results", []).append({"query": q, "result": result})
    new["current_query"] = None
    return new


def result_review_node(state: GraphState) -> GraphState:
    """
    节点 5：结果检查 / 归纳。

    目标：
    - 检查最新一条查询结果是否可用，并把结论沉淀为可追溯信息。

    实现策略：
    - 只检查 results 中最新追加的一条，避免重复扫描全部历史结果。
    - 主路径：在节点内部调用 LLM 判断状态，并输出结构化归纳。
    - 兜底路径：如果 LLM 连接失败、返回异常或解析失败，回退到本地启发式规则。
    - 根据结果文本判断状态：
      - ok: 可正常作为证据
      - empty: 像空结果 / 无数据
      - error: 像异常 / 失败信息
    - 无论状态如何，都会生成一条 evidence_summary 追加到状态中。
    - 如果是 empty 或 error：
      - 当前只记录 warnings / errors
      - 不自动生成补查 query，也不回插 plan
      - 等补查策略设计清楚后再扩展

    写回字段：
    - evidence_summary
    - warnings
    - errors
    - done
    """
    new = dict(state)
    results = new.get("results") or []
    if not results:
        return new

    latest = results[-1]
    query = (latest.get("query") or "").strip()
    result_text = latest.get("result") or ""

    status = "ok"
    llm_summary = summarize_result_text(result_text)
    try:
        llm, model = _get_llm_client()
        system = (
            "你是一个查询结果检查器。"
            "请根据 query 和 result 判断结果状态，只能返回 ok、empty、error 三类之一。"
            "同时给出一句简短中文摘要，以及是否建议补查。"
            "只输出 JSON，例如 "
            "{\"status\":\"ok\",\"summary\":\"...\",\"needs_follow_up\":false}。"
        )
        payload = {
            "task": "review_query_result",
            "labels": ["ok", "empty", "error"],
            "fewshots": [
                {
                    "query": "请查询：2025-03-01各站点最大雨量",
                    "result": "站点A 32.1mm，站点B 28.4mm，站点C 25.0mm。",
                    "output": {"status": "ok", "summary": "返回了多个站点的雨量结果，可直接作为证据。", "needs_follow_up": False},
                },
                {
                    "query": "请查询：2025-03-01三峡站超警情况",
                    "result": "未查询到相关数据。",
                    "output": {"status": "empty", "summary": "结果为空，当前未查到对应数据。", "needs_follow_up": True},
                },
                {
                    "query": "请查询：2025-03-01各站点流量",
                    "result": "Traceback: SQL execution failed due to timeout.",
                    "output": {"status": "error", "summary": "查询执行异常，像是服务超时。", "needs_follow_up": True},
                },
            ],
            "query": query,
            "result": result_text,
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
        content = (resp.choices[0].message.content or "").strip()
        obj = json.loads(content)
        status = str(obj.get("status") or "").strip().lower()
        if status not in {"ok", "empty", "error"}:
            raise RuntimeError(f"Invalid review status from LLM: {status}")
        llm_summary = str(obj.get("summary") or "").strip() or llm_summary
    except Exception as exc:
        print(f"[result_review] fallback to heuristic due to LLM failure: {exc}")
        if looks_like_error_result(result_text):
            status = "error"
        elif looks_like_empty_result(result_text):
            status = "empty"
        else:
            status = "ok"

    evidence_item = {
        "index": len(results),
        "query": query,
        "status": status,
        "summary": llm_summary,
        "supports_conclusion": status == "ok",
    }
    new.setdefault("evidence_summary", []).append(evidence_item)

    if status == "empty":
        append_unique(new.setdefault("warnings", []), f"查询“{query}”未返回有效数据。")
    elif status == "error":
        append_unique(new.setdefault("errors", []), f"查询“{query}”执行异常：{evidence_item['summary']}")

    new["done"] = not bool(new.get("plan"))
    return new


def write_report_node(state: GraphState) -> GraphState:
    """
    节点 6：最终输出。

    目标：
    - 在查询阶段结束后，把当前状态整理成用户可读的最终结果。

    分两种场景：
    - query:
      - 不调用写作模型
      - 直接把 results 格式化成查询汇总
    - report:
      - 调用 report_writer.generate 生成报告正文
      - 把 queries / outline / evidence_summary / warnings / errors 一起传入

    统一追加：
    - 无论 query 还是 report，最后都会追加 traceability appendix，
      用来明确哪些结论有证据、哪些查询失败、哪些地方有风险提示。
    """
    new = dict(state)
    if not new.get("done") or new.get("final_report"):
        return new

    meaning = (new.get("meaning") or "").lower()
    all_queries = new.get("all_queries_snapshot", [])
    all_results = new.get("results", [])

    if meaning == "query":
        body = format_query_results(all_results)
        appendix = build_traceability_appendix(new)
        new["final_report"] = body if not appendix else f"{body}\n\n{appendix}"
        return new

    if meaning != "report":
        new["final_report"] = "暂不支持该类型请求。当前仅支持直接查询和生成报告。"
        return new

    user_input = build_report_user_input(new["goal"], all_queries)
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

    appendix = build_traceability_appendix(new)
    new["final_report"] = report_body if not appendix else f"{report_body}\n\n{appendix}"
    return new
