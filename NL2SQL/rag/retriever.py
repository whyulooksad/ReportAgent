# 知识库检索
from pathlib import Path
from sentence_transformers import SentenceTransformer
from langchain_community.vectorstores import Chroma
from langchain_core.embeddings import Embeddings
from typing import List, Dict
from langchain_core.documents import Document
from NL2SQL.rag.path_config import CHROMA_DB_DIR, HF_MODEL_DIR, RULES_CHROMA_DB_DIR

class LocalBGEEmbeddings(Embeddings):
    def __init__(self, model_name=str(HF_MODEL_DIR)):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(text, show_progress_bar=False).tolist()

def load_retriever(persist_path: str = str(CHROMA_DB_DIR), top_k: int = 1):
    embedding = LocalBGEEmbeddings()
    db = Chroma(persist_directory=persist_path, embedding_function=embedding)
    return db.as_retriever(search_kwargs={"k": top_k})

def retrieve_context(query: str, persist_path: str = str(CHROMA_DB_DIR), top_k: int = 1):
    retriever = load_retriever(persist_path, top_k)
    docs = retriever.get_relevant_documents(query)
    return docs


def get_field_docs_by_tables(table_names: List[str]) -> List[Document]:
    embedding = LocalBGEEmbeddings()
    db = Chroma(persist_directory=str(CHROMA_DB_DIR), embedding_function=embedding)

    all_docs = []
    for name in table_names:
        docs = db.similarity_search("", k=3, filter={"table": name})
        all_docs.extend(docs)
    return all_docs


# def get_rules_by_knowledgecontent(query: str) -> List[Document]:
#     """
#     对 knowledgecontent 进行相似度检索
#     """
#     embedding = LocalBGEEmbeddings()
#     db = Chroma(persist_directory=str(RULES_CHROMA_DB_DIR), embedding_function=embedding)
#
#     # 使用相似度搜索查找相关的知识内容
#     docs = db.similarity_search(query, k=3)
#     return docs

def get_rules_by_knowledgecontent(query: str, score_threshold: float = 0.7) -> List[Document]:
    """
    对 knowledgecontent 进行相似度检索

    Args:
        query: 查询内容
        score_threshold: 置信度阈值 (0-1之间)，默认0.7，值越高要求匹配度越高

    Returns:
        List[Document]: 满足置信度阈值条件的文档列表，如果没有符合条件的文档则返回空列表
    """
    embedding = LocalBGEEmbeddings()
    db = Chroma(persist_directory=str(RULES_CHROMA_DB_DIR), embedding_function=embedding)

    # 使用带分数的相似度搜索
    docs_with_scores = db.similarity_search_with_score(query, k=5)  # 先获取较多结果

    # 根据置信度阈值过滤结果
    filtered_docs = []
    for doc, score in docs_with_scores:
        # 注意：Chroma 返回的是距离分数，越小表示越相似
        # 我们将其转换为置信度 (1 - 距离)
        confidence = 1 - score
        if confidence >= score_threshold:
            # 将置信度添加到文档元数据中
            doc.metadata["confidence"] = round(confidence, 3)
            filtered_docs.append(doc)

    # 只返回满足阈值条件的文档，如果没有则返回空列表
    return filtered_docs


if __name__ == "__main__":
    docs = get_field_docs_by_tables(["public.st_pptn_r"])
    for doc in docs:
        print(" 表名：", doc.metadata.get("table"))
        print(" 字段解释内容：")
        print(doc.page_content)
        print("-" * 60)

