# 文本分块
from pathlib import Path
import re
from typing import List, Dict
import pymysql
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def parse_schema_md_by_table(md_text: str) -> List[Dict]:
    """
    将 markdown 内容按表切块，每个表一个 chunk，内容为整个表的字段说明
    """
    entries = []
    lines = md_text.splitlines()

    current_table = None
    current_chunk = []

    for line in lines:
        table_match = re.match(r'^### 表名[:：]?\s*([a-zA-Z0-9_.]+)', line)
        if table_match:
            if current_table and current_chunk:
                entries.append({
                    "content": "\n".join(current_chunk).strip(),
                    "metadata": {"table": current_table}
                })
                current_chunk = []
            current_table = table_match.group(1)
            current_chunk.append(f"【表名】{current_table}")
        elif current_table:
            current_chunk.append(line)

    if current_table and current_chunk:
        entries.append({
            "content": "\n".join(current_chunk).strip(),
            "metadata": {"table": current_table}
        })

    return entries


def parse_knowledge_from_db() -> List[Dict]:
    """
    从 knowledge 表按条分块，每条 knowledgecontent 为一个 chunk
    """
    entries = []

    try:
        # 连接数据库
        connection = pymysql.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', 3306)),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', 'stw456852'),
            database=os.getenv('DB_NAME', 'waterknow'),
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # 查询所有 knowledge 记录
            sql = "SELECT knowledgeid, knowledgecontent, updatetime, userid FROM knowledge WHERE knowledgecontent IS NOT NULL AND knowledgecontent != ''"
            cursor.execute(sql)
            results = cursor.fetchall()

            for row in results:
                knowledgeid, knowledgecontent, updatetime, userid = row

                # 为每条知识创建一个 chunk
                entries.append({
                    "content": knowledgecontent.strip(),
                    "metadata": {
                        "knowledgeid": knowledgeid,
                        "updatetime": str(updatetime) if updatetime else None,
                        "userid": userid,
                        "source": "knowledge"
                    }
                })

    except Exception as e:
        print(f"从 knowledge 表加载数据时出错: {e}")
    finally:
        if 'connection' in locals() and connection.open:
            connection.close()

    return entries


def get_all_chunks() -> List[Dict]:
    """
    获取所有分块，包括 schema 分块和 knowledge 分块
    """
    chunks = []

    # 如果有 schema markdown 文件，可以在这里调用 parse_schema_md_by_table
    # chunks.extend(parse_schema_md_by_table(schema_md_content))

    # 添加 knowledge 表的分块
    chunks.extend(parse_knowledge_from_db())

    return chunks




