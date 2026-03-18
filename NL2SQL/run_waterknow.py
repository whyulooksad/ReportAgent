import os
from pathlib import Path

import mysql.connector


conn = mysql.connector.connect(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
)
cursor = conn.cursor()

sql_path = Path(__file__).with_name("waterknow.sql")
with sql_path.open("r", encoding="utf-8") as f:
    sql_script = f.read()

# 按分号分割 SQL 语句逐条执行
for statement in sql_script.split(';'):
    stmt = statement.strip()
    if stmt:
        try:
            cursor.execute(stmt)
        except Exception as e:
            print(f"执行失败：{stmt[:50]}...\n错误：{e}\n")

conn.commit()
cursor.close()
conn.close()
print("waterknow.sql 执行完成！")
