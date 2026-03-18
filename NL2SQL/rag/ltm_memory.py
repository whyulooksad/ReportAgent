#长期记忆管理器
# rag/ltm_memory.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional

from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from NL2SQL.rag.retriever import LocalBGEEmbeddings
from pathlib import Path
from NL2SQL.rag.path_config import LTM_CHROMA_DB_DIR


@dataclass
class LTMConfig:
    # 用“单独目录”来物理隔离长期记忆，避免与外部资料向量库混在一起
    persist_path: str = str(LTM_CHROMA_DB_DIR)  # 直接使用 LTM_CHROMA_DB_DIR 配置
    collection_name: str = "long_term_memory"
    top_k: int = 3


class LongTermMemory:
    def __init__(self, cfg: Optional[LTMConfig] = None):
        self.cfg = cfg or LTMConfig()
        self.embedding = LocalBGEEmbeddings()
        Path(self.cfg.persist_path).mkdir(parents=True, exist_ok=True)
        self.vs = Chroma(
            persist_directory=self.cfg.persist_path,
            embedding_function=self.embedding,
            collection_name=self.cfg.collection_name
        )

    def add_memory(self, text: str, metadata: Optional[Dict] = None):
        """
        写入一条长期记忆。建议 text 为用户查询内容，metadata 包含 SQL 查询或其他相关信息。
        metadata 示例：{"sql": "SELECT * FROM rain_data WHERE date = '2025-09-08'"}
        """
        if not text or not text.strip():
            return
        doc = Document(page_content=text.strip(), metadata=metadata or {})
        self.vs.add_documents([doc])
        self.vs.persist()

    def search_memories(self, query: str, k: Optional[int] = None) -> List[Document]:
        k = k or self.cfg.top_k
        return self.vs.similarity_search(query, k=k)



