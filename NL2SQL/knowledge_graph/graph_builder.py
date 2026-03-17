# 构建知识图谱
import os
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine
from py2neo import Graph, Node, Relationship
from schema_engine.schema_engine import SchemaEngine

load_dotenv()

SCHEMA_DEFAULT = "dbo"

def qualify_table(table_name: str, schema: str = SCHEMA_DEFAULT) -> str:
    """确保表名是 schema.table 形式"""
    parts = table_name.split(".")
    if len(parts) == 1:
        return f"{schema}.{parts[0]}"
    if len(parts) >= 2:
        # 已包含 schema 就原样返回
        return f"{parts[0]}.{parts[1]}"
    return table_name

def qualify_column(col_name: str, schema: str = SCHEMA_DEFAULT) -> str:
    """确保列名是 schema.table.column 形式"""
    parts = col_name.split(".")
    if len(parts) == 1:
        # 只有列名，不知道表，保持原样（一般不会出现）
        return col_name
    if len(parts) == 2:
        # table.column  -> 补 schema
        return f"{schema}.{parts[0]}.{parts[1]}"
    if len(parts) >= 3:
        # 已是 schema.table.column
        return f"{parts[0]}.{parts[1]}.{parts[2]}"
    return col_name

def build_schema_graph():
    """
    从数据库读取表结构，构建 Neo4j 知识图谱
    同时支持从 table_relations.json 加载人工外键关系
    """
    # 连接 Neo4j
    graph = Graph(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
    )

    # 连接数据库，读取 MSchema
    db_uri = os.getenv("DB_URI")
    db_engine = create_engine(db_uri)

    schema_engine = SchemaEngine(
        engine=db_engine,
        schema=SCHEMA_DEFAULT,  # 只查 dbo
        include_tables=[
            'ST_TABLE_D',
            'ST_FIELD_D',
            'ST_PPTN_R',
            'ST_RIVER_R',
            'ST_HIWRCH_B',
            'ST_STBPRP_B',
            'ST_ADDVCD_D',
            'ST_RVFCCH_B',
            'ST_FORECAST_F'
        ]
    )

    mschema_obj = schema_engine.mschema

    # 清空旧图谱
    print("清空 Neo4j 旧图谱数据...")
    graph.delete_all()

    # 创建表节点和字段节点（统一加 schema 前缀 + 双向 HAS_COLUMN）
    print("开始写入表和字段节点...")
    for table, table_info in mschema_obj.tables.items():
        fq_table = qualify_table(table)
        table_node = Node("Table", name=fq_table, comment=table_info.get('comment', ''))
        graph.merge(table_node, "Table", "name")

        for field_name, field_info in table_info["fields"].items():
            fq_col = qualify_column(f"{table}.{field_name}")
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
        fq_col1 = qualify_column(f"{table1}.{col1}")
        fq_col2 = qualify_column(f"{table2}.{col2}")
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
            from_col = qualify_column(rel["from"])
            to_col = qualify_column(rel["to"])

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
