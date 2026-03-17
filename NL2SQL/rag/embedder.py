# 构建向量知识库

import os
from pathlib import Path
from sentence_transformers import SentenceTransformer
from langchain_community.vectorstores import Chroma
from langchain_core.embeddings import Embeddings
from langchain.schema import Document
from rag.loader import parse_schema_md_by_table,parse_knowledge_from_db
from rag.path_config import CHROMA_DB_DIR, HF_MODEL_DIR,RULES_CHROMA_DB_DIR,ensure_dirs
import shutil

ensure_dirs()
class LocalBGEEmbeddings(Embeddings):
    def __init__(self, model_name=str(HF_MODEL_DIR)):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(text, show_progress_bar=False).tolist()

def build_chroma_from_md(md_path: str, persist_path: str = str(CHROMA_DB_DIR)):
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    parsed_docs = parse_schema_md_by_table(md_text)
    documents = [
        Document(page_content=doc["content"], metadata=doc["metadata"])
        for doc in parsed_docs
    ]

    embedding = LocalBGEEmbeddings()
    db = Chroma.from_documents(documents, embedding, persist_directory=persist_path)
    db.persist()
    print(f" 本地向量库（按表切分）构建完成，保存路径：{persist_path}")


def build_chroma_from_knowledge(persist_path: str = str(RULES_CHROMA_DB_DIR)):
    """
    从 knowledge 表构建向量库
    """
    # 获取 knowledge 表的分块数据
    knowledge_chunks = parse_knowledge_from_db()

    if not knowledge_chunks:
        print("未找到 knowledge 表数据，向量库构建终止")
        return None

    # 转换为 Document 对象
    documents = [
        Document(page_content=doc["content"], metadata=doc["metadata"])
        for doc in knowledge_chunks
    ]

    # 创建嵌入模型
    embedding = LocalBGEEmbeddings()

    # 构建向量库
    db = Chroma.from_documents(
        documents=documents,
        embedding=embedding,
        persist_directory=persist_path
    )

    db.persist()
    print(f"Knowledge 向量库构建完成，共处理 {len(documents)} 条知识，保存路径：{persist_path}")
    return db



if __name__ == "__main__":
    build_chroma_from_md("D:/Work/sqldata/docs/schema_doc.md")
    # build_chroma_from_knowledge()
