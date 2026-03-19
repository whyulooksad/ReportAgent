# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class GraphState(TypedDict):
    """
    LangGraph 在节点之间传递的统一状态。

    字段说明：
    - goal: 用户原始输入。
    - plan: 尚未执行的自然语言查询队列，scheduler 每轮取出一条。
    - current_query: 当前准备发送给 NL2SQL 的单条查询。
    - results: 已完成查询的结果列表，每项为 {"query": str, "result": str}。
    - iterations: 调度轮次计数，便于排查流程是否重复回环。
    - done: 是否已经没有剩余查询需要执行。
    - final_report: 最终输出文本；query 场景下是结果汇总，report 场景下是报告正文及附录。
    - all_queries_snapshot: 查询任务全量快照，用于写报告时按原顺序对齐结果。
    - meaning: 意图分类结果，取值通常为 query / report / other。
    - template_name: 报告场景下选中的模板名称。
    - report_type: 预留字段，后续可用于区分周报、月报等报告类型。
    - time: 从用户输入中提取到的时间提示。
    - errors: 查询或归纳阶段确认失败的问题列表。
    - warnings: 空结果、补查、口径风险等非致命提示。
    - evidence_summary: 每条查询沉淀出的证据摘要，供最终输出说明“哪些结论有数据支撑”。
    - outline: 报告提纲或查询任务纲要，供写作和最终展示使用。
    - review_retry_counts: 记录每条原始查询已经触发过几次补查，避免无限循环。
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
    errors: List[str]
    warnings: List[str]
    evidence_summary: List[Dict[str, Any]]
    outline: List[str]
    review_retry_counts: Dict[str, int]
