#后端隐式时区注入
from datetime import datetime
from zoneinfo import ZoneInfo

def build_hidden_system_context(
    timezone: str = "Asia/Shanghai",
    extra_notes: str | None = None,
) -> str:
    """
    构造隐藏的系统上下文。包含当前时间与时区，可按需扩展更多运行时信息。
    这段文本将作为“最前置的 system 消息”注入，但不写入你的会话记忆。
    """
    now = datetime.now(ZoneInfo(timezone))
    # 你可以按需扩展更多字段：ISO、epoch、周数、工作日等
    iso_date = now.strftime("%Y-%m-%d")
    iso_time = now.strftime("%H:%M:%S %Z")
    base = [
        f"RUNTIME_CONTEXT:",
        f"- now_local: {iso_date} {iso_time}",
        f"- timezone: {timezone}",
        f"- today: {iso_date}",
        "Guidelines:",
        "- Treat the time above as the source of truth for any time/date questions.",
        "- Do not guess current date/time from training cutoffs.",
    ]
    if extra_notes:
        base.append(f"- notes: {extra_notes}")
    return "\n".join(base)