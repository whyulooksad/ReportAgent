import os
import json
import time
from pathlib import Path
import re

from NL2SQL.config.settings import DB_SCHEMA, DB_URI, INCLUDE_TABLES
from NL2SQL.schema_engine.schema_engine import SchemaEngine
from sqlalchemy import create_engine

def main():
    project_root = Path(__file__).resolve().parent
    cache_dir = project_root / "schema_cache"
    # 确保递归创建目录，避免上层目录缺失时报错
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "schema.json"

    print("正在生成 schema 缓存（现场连库）...")
    db_engine = create_engine(DB_URI)
    schema_engine = SchemaEngine(
        engine=db_engine,
        schema=DB_SCHEMA,
        include_tables=INCLUDE_TABLES,
    )
    mschema_obj = schema_engine.mschema
    schema_text = mschema_obj.to_mschema()
    mschema_dump = mschema_obj.dump()

    txt = (schema_text or "").replace("\r\n", "\n")
    tables_count = len(re.findall(r'(?mi)^\s*#\s*Table\s*:', txt))

    payload = {
        "schema_data": schema_text,
        "mschema_dump": mschema_dump,
        "timestamp": int(time.time()),
        "tables_count": tables_count,
    }

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"已写入缓存：{cache_file}")
    print(f"表数≈{tables_count}，时间={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(payload['timestamp']))}")

if __name__ == "__main__":
    main()
