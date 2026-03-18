from NL2SQL.rag.ltm_memory import LTMConfig, LongTermMemory

# 使用默认配置（LTM_CHROMA_DB_DIR/long_term_memory）
cfg = LTMConfig()
ltm = LongTermMemory(cfg=cfg)

# 直接访问底层 Chroma collection
collection = ltm.vs._collection   # 注意：这是内部属性，但可以用来查看数据

print("当前存储的文档数量：", collection.count())

# 打印所有文档（内容 + metadata）
docs = collection.get(include=["metadatas", "documents"])
for i, (doc, meta) in enumerate(zip(docs["documents"], docs["metadatas"])):
    print(f"\n--- 记录 {i+1} ---")
    print("内容:", doc)
    print("元数据:", meta)
