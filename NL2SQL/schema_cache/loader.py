import os
import json
import time
from typing import Tuple

# 缓存文件放在当前目录下（即 schema_cache/schema.json）
CACHE_FILE = os.path.join(os.path.dirname(__file__), "schema.json")

def _read_cache() -> Tuple[str, int, int]:
    """
    读取缓存文件，返回 (schema_text, timestamp, tables_count)
    如果文件不存在或字段不完整，抛出 RuntimeError。
    """
    if not os.path.exists(CACHE_FILE):
        raise RuntimeError(
            f"[schema_cache] 缓存文件不存在：{CACHE_FILE}\n"
            f"请先运行预热脚本 get_schema_cache.py 生成缓存。"
        )
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        schema_text = data.get("schema_data", "")
        ts = int(data.get("timestamp", 0))
        tables_count = int(data.get("tables_count", 0))
        if not schema_text or ts <= 0:
            raise ValueError("字段缺失或为空")
        return schema_text, ts, tables_count
    except Exception as e:
        raise RuntimeError(
            f"[schema_cache] 读取缓存失败：{e}\n"
            f"请重新运行预热脚本 prewarm_schema_cache.py 生成缓存。"
        )

def get_schema() -> str:
    """
    只读：返回缓存中的 schema 文本。
    不会尝试连库或运行任何生成逻辑。
    """
    schema_text, ts, tables_count = _read_cache()
    # 如需在日志里看到缓存信息，可取消下一行注释
    # print(f"[schema_cache] 命中缓存，时间={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}, 表数≈{tables_count}")
    return schema_text
