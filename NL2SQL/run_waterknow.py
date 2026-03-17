import mysql.connector

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="stw456852"
)
cursor = conn.cursor()

with open("waterknow.sql", "r", encoding="utf-8") as f:
    sql_script = f.read()

# 按分号分割 SQL 语句逐条执行
for statement in sql_script.split(';'):
    stmt = statement.strip()
    if stmt:
        try:
            cursor.execute(stmt)
        except Exception as e:
            print(f"❌ 执行失败：{stmt[:50]}...\n错误：{e}\n")

conn.commit()
cursor.close()
conn.close()
print("✅ waterknow.sql 执行完成！")
