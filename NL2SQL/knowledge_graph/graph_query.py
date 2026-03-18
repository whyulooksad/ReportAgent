from py2neo import Graph

from NL2SQL.config.settings import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, qualify_column_name

class SchemaGraphQuery:
    def __init__(self):
        self.graph = Graph(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )

    def find_path(self, start_column: str, end_column: str):
        """
        查找两列之间的最短路径（返回列节点路径）
        自动补齐 schema 前缀
        """
        start_column = qualify_column_name(start_column)
        end_column = qualify_column_name(end_column)

        query = """
        MATCH p = shortestPath(
            (start:Column {name: $start})-[:FOREIGN_KEY_TO|HAS_COLUMN*1..5]-(end:Column {name: $end})
        )
        RETURN p
        """
        result = self.graph.run(query, start=start_column, end=end_column).data()
        if not result:
            return None
        return result[0]['p']

    def extract_tables_from_path(self, path):
        """
        从路径中提取涉及的表名
        """
        tables = set()
        for node in path.nodes:
            if "Table" in node.labels:
                tables.add(node["name"])
            elif "Column" in node.labels:
                table_name = node["name"].rsplit(".", 1)[0]
                tables.add(table_name)
        return list(tables)

if __name__ == "__main__":
    sq = SchemaGraphQuery()
    p = sq.find_path("dbo.ST_PPTN_R.STCD", "dbo.ST_ADDVCD_D.ADDVCD")
    if p:
        print("路径节点：", [n["name"] for n in p.nodes])
        print("涉及表：", sq.extract_tables_from_path(p))
    else:
        print("没找到路径")
