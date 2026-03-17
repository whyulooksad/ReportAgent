from rag.retriever import load_retriever
from rag.retriever import LocalBGEEmbeddings
from langchain_community.vectorstores import Chroma
from rag.path_config import RULES_CHROMA_DB_DIR


# 查看 chroma_rules 向量库中的内容
embedding = LocalBGEEmbeddings()
db = Chroma(persist_directory=str(RULES_CHROMA_DB_DIR), embedding_function=embedding)
docs = db.get()["documents"]
metas = db.get()["metadatas"]
for i in range(len(metas)):
    print(f"文档 {i+1}: 知识ID →", metas[i].get("knowledgeid"))
    print("内容预览:", docs[i][:100])
    print("-" * 40)

# 查看 chroma_db 向量库中的内容
# retriever = load_retriever()
# docs = retriever.vectorstore.get()["documents"]
# metas = retriever.vectorstore.get()["metadatas"]
#
# for i in range(len(metas)):
#     print(f" 文档 {i+1}: 表名 →", metas[i].get("table"))
#     print("内容预览:", docs[i][:100])
#     print("-" * 40)
