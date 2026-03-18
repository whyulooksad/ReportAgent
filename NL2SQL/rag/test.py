from NL2SQL.rag.loader import parse_schema_md_by_table

with open("D:/Work/sqldata/docs/schema_doc.md", encoding="utf-8") as f:
    md_text = f.read()

entries = parse_schema_md_by_table(md_text)
print(" 表总数：", len(entries))
for entry in entries:
    print(" 表名:", entry["metadata"]["table"])
