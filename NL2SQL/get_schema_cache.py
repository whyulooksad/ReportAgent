import os
import json
import time
from schema_engine.xiyan import mschema  #
from pathlib import Path
import re

def main():
    project_root = Path(__file__).resolve().parent
    cache_dir = project_root / "schema_cache"
    # 确保递归创建目录，避免上层目录缺失时报错
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "schema.json"

    print("正在生成 schema 文本（现场连库）...")
    schema_text = mschema()  # 确保环境变量/连接可用

    txt = (schema_text or "").replace("\r\n", "\n")
    tables_count = len(re.findall(r'(?mi)^\s*#\s*Table\s*:', txt))

    payload = {
        "schema_data": schema_text,
        "timestamp": int(time.time()),
        "tables_count": tables_count,
    }

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"已写入缓存：{cache_file}")
    print(f"表数≈{tables_count}，时间={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(payload['timestamp']))}")

if __name__ == "__main__":
    main()
