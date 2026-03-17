# 统一路径
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()  # 允许 .env 覆盖

# 统一：知识库目录（Chroma）
# 例：D:/Work/NL2SQL/chroma_db  或  项目内 rag/chroma_db
CHROMA_DB_DIR = Path(os.getenv("CHROMA_DB_DIR", Path(__file__).resolve().parent / "chroma_db")).resolve()

# 统一：本地嵌入模型目录（HF）
# D:/Work/NL2SQL/hf_models/bge-small-zh
HF_MODEL_DIR = Path(os.getenv("HF_MODEL_DIR", r"D:\Work\sqldata\hf_models\bge-small-zh")).resolve()

#长期记忆的 Chroma 数据库目录
LTM_CHROMA_DB_DIR = Path(os.getenv("LTM_CHROMA_DB_DIR", "D:/Work/sqldata/rag/chroma_ltm")).resolve()

#规则库目录
RULES_CHROMA_DB_DIR = Path(os.getenv("RULES_CHROMA_DB_DIR", "D:/Work/sqldata/rag/chroma_rules")).resolve()

def ensure_dirs():
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    LTM_CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    RULES_CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
