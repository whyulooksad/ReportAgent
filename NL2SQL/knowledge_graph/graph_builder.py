import json
import re
from sqlalchemy import create_engine
from py2neo import Graph, Node, Relationship
import os

from NL2SQL.config.settings import (
    DB_SCHEMA,
    DB_URI,
    INCLUDE_TABLES,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    qualify_column_name,
    qualify_table_name,
)
from NL2SQL.schema_engine.m_schema import MSchema
from NL2SQL.schema_engine.schema_engine import SchemaEngine


def _parse_examples(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load_mschema_from_cache() -> MSchema | None:
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "schema_cache",
        "schema.json",
    )
    if not os.path.exists(cache_path):
        return None

    with open(cache_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    cached_dump = payload.get("mschema_dump")
    if isinstance(cached_dump, dict) and cached_dump.get("tables"):
        mschema_obj = MSchema()
        mschema_obj.db_id = cached_dump.get("db_id", "Anonymous")
        mschema_obj.schema = cached_dump.get("schema", DB_SCHEMA)
        mschema_obj.tables = cached_dump.get("tables", {})
        mschema_obj.foreign_keys = cached_dump.get("foreign_keys", [])
        print(f"命中结构化 schema 缓存: {cache_path}")
        return mschema_obj

    schema_text = payload.get("schema_data", "")
    if not schema_text:
        return None

    print(f"命中文本 schema 缓存: {cache_path}")
    mschema_obj = MSchema(db_id=payload.get("db_id", ""), schema=DB_SCHEMA)
    current_table = None
    in_fk_section = False

    for raw_line in schema_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "【Foreign keys】":
            in_fk_section = True
            current_table = None
            continue
        if in_fk_section:
            if "=" in line:
                left, right = line.split("=", 1)
                left_parts = left.split(".")
                right_parts = right.split(".")
                if len(left_parts) >= 2 and len(right_parts) >= 2:
                    mschema_obj.add_foreign_key(
                        left_parts[-2],
                        left_parts[-1],
                        DB_SCHEMA,
                        right_parts[-2],
                        right_parts[-1],
                    )
            continue

        table_match = re.match(r"^# Table:\s+(?:[^.]+\.)?([A-Za-z0-9_]+)", line)
        if table_match:
            current_table = table_match.group(1)
            mschema_obj.add_table(current_table, fields={}, comment="")
            continue

        if not current_table or line in {"[", "]"}:
            continue

        field_match = re.match(r"^\(([^:]+):([^,)\]]+)(.*)\),?$", line)
        if not field_match:
            continue

        field_name = field_match.group(1).strip()
        field_type = field_match.group(2).strip()
        extras = field_match.group(3)
        primary_key = "Primary Key" in extras
        examples_match = re.search(r"Examples:\s*\[(.*)\]", extras)
        examples = _parse_examples(examples_match.group(1)) if examples_match else []

        mschema_obj.add_field(
            current_table,
            field_name,
            field_type=field_type,
            primary_key=primary_key,
            examples=examples,
        )

    return mschema_obj

def build_schema_graph():
    """
    从数据库读取表结构，构建 Neo4j 知识图谱
    同时支持从 table_relations.json 加载人工外键关系
    """
    # 连接 Neo4j
    graph = Graph(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD)
    )

    mschema_obj = _load_mschema_from_cache()
    if mschema_obj is None:
        print("未命中 schema 缓存，回退为现场连库读取结构...")
        db_engine = create_engine(DB_URI)
        schema_engine = SchemaEngine(
            engine=db_engine,
            schema=DB_SCHEMA,
            include_tables=INCLUDE_TABLES,
        )
        mschema_obj = schema_engine.mschema

    # 清空旧图谱
    print("清空 Neo4j 旧图谱数据...")
    graph.delete_all()

    # 创建表节点和字段节点（统一加 schema 前缀 + 双向 HAS_COLUMN）
    print("开始写入表和字段节点...")
    for table, table_info in mschema_obj.tables.items():
        fq_table = qualify_table_name(table)
        table_node = Node("Table", name=fq_table, comment=table_info.get('comment', ''))
        graph.merge(table_node, "Table", "name")

        for field_name, field_info in table_info["fields"].items():
            fq_col = qualify_column_name(f"{table}.{field_name}")
            col_node = Node(
                "Column",
                name=fq_col,
                type=field_info.get("type", ""),
                comment=field_info.get("comment", "")
            )
            graph.merge(col_node, "Column", "name")
            # 双向 HAS_COLUMN
            graph.merge(Relationship(table_node, "HAS_COLUMN", col_node))
            graph.merge(Relationship(col_node, "HAS_COLUMN", table_node))

    # 创建数据库原生外键关系（两端统一补全）
    print("写入数据库本身的外键关系...")
    for fk in mschema_obj.foreign_keys:
        table1, col1, _, table2, col2 = fk
        fq_col1 = qualify_column_name(f"{table1}.{col1}")
        fq_col2 = qualify_column_name(f"{table2}.{col2}")
        col_node1 = Node("Column", name=fq_col1)
        col_node2 = Node("Column", name=fq_col2)
        graph.merge(col_node1, "Column", "name")
        graph.merge(col_node2, "Column", "name")
        graph.merge(Relationship(col_node1, "FOREIGN_KEY_TO", col_node2))
        graph.merge(Relationship(col_node2, "FOREIGN_KEY_TO", col_node1))

    # 加载人工外键配置（两端也做补全，避免 JSON 写成短名时出错）
    # manual_fk_path = "table_relations.json"
    manual_fk_path = os.path.join(os.path.dirname(__file__), "table_relations.json")

    if os.path.exists(manual_fk_path):
        print(f"检测到人工外键配置文件: {manual_fk_path}，开始加载...")
        with open(manual_fk_path, "r", encoding="utf-8") as f:
            manual_fks = json.load(f)

        for rel in manual_fks:
            from_col = qualify_column_name(rel["from"])
            to_col = qualify_column_name(rel["to"])

            col_node1 = Node("Column", name=from_col)
            col_node2 = Node("Column", name=to_col)
            graph.merge(col_node1, "Column", "name")
            graph.merge(col_node2, "Column", "name")
            graph.merge(Relationship(col_node1, "FOREIGN_KEY_TO", col_node2))
            graph.merge(Relationship(col_node2, "FOREIGN_KEY_TO", col_node1))

        print(f"已加载 {len(manual_fks)} 条人工外键关系。")
    else:
        print("未检测到 table_relations.json，跳过人工外键加载。")

    print("知识图谱构建完成！")

if __name__ == "__main__":
    build_schema_graph()
