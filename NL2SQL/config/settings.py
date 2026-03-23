from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

DB_URI = os.getenv("DB_URI", "")
DB_SCHEMA = os.getenv("DB_SCHEMA", "")

INCLUDE_TABLES = [
    "ST_TABLE_D",
    "ST_FIELD_D",
    "ST_PPTN_R",
    "ST_RIVER_R",
    "ST_STBPRP_B",
    "ST_ADDVCD_D",
    "ST_RVFCCH_B",
    "ST_FORECAST_F",
    "ST_HIWRCH_B",
]

DASHSCOPE_APIKEY = os.getenv("DASHSCOPE_APIKEY", "")
BASE_URL = os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
NL2SQL_MODEL = os.getenv("NL2SQL_MODEL", "qwen3-max")

SERVICE_HOST = os.getenv("NL2SQL_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("NL2SQL_PORT", "8001"))
SERVICE_PATH = os.getenv("NL2SQL_PATH", "/nl2sql")

CHROMA_DB_DIR = Path(os.getenv("CHROMA_DB_DIR", PACKAGE_ROOT / "rag" / "chroma_db")).resolve()
LTM_CHROMA_DB_DIR = Path(os.getenv("LTM_CHROMA_DB_DIR", PACKAGE_ROOT / "rag" / "chroma_ltm")).resolve()
RULES_CHROMA_DB_DIR = Path(os.getenv("RULES_CHROMA_DB_DIR", PACKAGE_ROOT / "rag" / "chroma_rules")).resolve()
HF_MODEL_DIR = Path(os.getenv("HF_MODEL_DIR", PACKAGE_ROOT / "hf_models" / "bge-small-zh")).resolve()

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USER = os.getenv("NEO4J_USER", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


def ensure_dirs() -> None:
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    LTM_CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
    RULES_CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)


def qualify_table_name(table_name: str) -> str:
    if not table_name:
        return table_name
    return table_name if "." in table_name else f"{DB_SCHEMA}.{table_name}"


def qualify_column_name(column_name: str) -> str:
    parts = (column_name or "").split(".")
    if len(parts) == 2:
        return f"{DB_SCHEMA}.{parts[0]}.{parts[1]}"
    if len(parts) >= 3:
        return f"{parts[0]}.{parts[1]}.{parts[2]}"
    return column_name
