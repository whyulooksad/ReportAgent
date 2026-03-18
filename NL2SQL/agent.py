# NL2SQL智能体
import datetime
import threading
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from langchain_core.prompts import ChatPromptTemplate
from typing import Dict, List

from sqlalchemy import create_engine
from sqlalchemy.sql import text
from tabulate import tabulate
from NL2SQL.config.settings import BASE_URL, DASHSCOPE_APIKEY, DB_URI, NL2SQL_MODEL
from NL2SQL.knowledge_graph.graph_query import SchemaGraphQuery
from NL2SQL.rag.path_config import CHROMA_DB_DIR
from NL2SQL.rag.retriever import get_field_docs_by_tables, get_rules_by_knowledgecontent, load_retriever
from NL2SQL.runtime_context import build_hidden_system_context
from NL2SQL.schema_cache import get_schema

__AGENT_INITIALIZED = False
__AGENT_INIT_LOCK = threading.Lock()

MAX_TOOL_RETURN_CHARS = 5000  # 控制传给 LLM 的结果长度

engine = create_engine(DB_URI)
retriever = load_retriever(persist_path=str(CHROMA_DB_DIR))

llm = ChatOpenAI(
    api_key=DASHSCOPE_APIKEY,
    base_url=BASE_URL,
    model=NL2SQL_MODEL,
)

# ===== 惰性初始化（schema + 会话记忆）BEGIN =====
def _init_agent_once():
    """
    仅执行一次：
    - 读取数据库结构（只从缓存：get_schema()）
    - 注入到记忆（conversation_memory.set_schema(...)）
    """
    global __AGENT_INITIALIZED
    schema_info = get_schema()                          # 你已有的函数
    conversation_memory.set_schema(schema_info)      # 你已有的记忆体
    __AGENT_INITIALIZED = True
    try:
        print("[agent] schema 已加载进记忆。")
    except Exception:
        pass

def _ensure_initialized():
    """
    对外不可见：保证首次调用前一定已完成初始化（线程安全）
    """
    global __AGENT_INITIALIZED
    if __AGENT_INITIALIZED:
        return
    with __AGENT_INIT_LOCK:
        if not __AGENT_INITIALIZED:
            _init_agent_once()
# ===== 惰性初始化（schema + 会话记忆）END =====


def _cap(s: str) -> str:
    """截断过长的工具输出，避免撑爆 LLM 输入"""
    if not s:
        return ""
    return s if len(s) <= MAX_TOOL_RETURN_CHARS else s[:MAX_TOOL_RETURN_CHARS] + "...(truncated)"

def run_sql_query(query: str):
    """
    执行传入的 SQL 查询，并以表格格式输出。
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            columns = result.keys()

            if rows:
                res = tabulate(rows, headers=columns, tablefmt="grid", stralign="center")
                print(res)
                return res
            else:
                print("查询成功，但无返回结果。")
    except Exception as e:
        print(f"SQL 执行错误：{e}")
        return str(e)

# @tool
# def file_saver(content: str, filename: str) -> str:
#     """
#     当需要写入文件的时候，可以使用该工具
#     Args:
#         content: 需要写入的文件内容
#         filename: 文件名称
#     """
#     with open(filename, "w", encoding="utf-8") as f:
#         f.write(content)
#     return "文件写入成功"

# @tool
# def execute_sql(sql: str):
#     """根据提供的sql语句来执行sql,并返回执行后的结果"""
#     print(sql)
#     return run_sql_query(sql)
@tool
def execute_sql(sql: str):
    """根据提供的sql语句来执行sql,并返回执行后的结果"""
    print(sql)
    result = run_sql_query(sql)
    return _cap(result)


@tool
def retrieve_field_docs(table_names: List[str]) -> str:
    """根据表名从知识库中检索字段解释。必须在生成SQL之前先调用。"""
    docs = get_field_docs_by_tables(table_names)
    return "\n\n".join([doc.page_content for doc in docs])


@tool
def retrieve_rules_docs(query: str) -> str:
    """根据查询内容从规则库中检索相关知识内容。用于获取业务规则、数据格式等信息。"""
    docs = get_rules_by_knowledgecontent(query, score_threshold=0.5)
    if not docs:
        return ""  # 返回空字符串
    return "\n\n".join([doc.page_content for doc in docs])

@tool
def find_join_path(start_column: str, end_column: str) -> str:
    """
    在 Neo4j 知识图谱中查找起点列到终点列的最短路径，并返回涉及的表和结构说明。
    """
    sq = SchemaGraphQuery()
    path = sq.find_path(start_column, end_column)
    if not path:
        return "未找到路径"

    # 获取涉及的表
    tables = sq.extract_tables_from_path(path)
    # schema_info = conversation_memory.schema_info or "无表结构信息"

    # 返回路径节点和涉及的表结构说明
    # return f"涉及的表: {tables}，路径节点: {[n['name'] for n in path.nodes]}\n表结构说明: {schema_info}"
    return f"涉及的表: {tables}，路径节点: {[n['name'] for n in path.nodes]}"


agent = initialize_agent(
    tools=[execute_sql,retrieve_field_docs,find_join_path,retrieve_rules_docs],
    llm=llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    handle_parsing_errors=True,
    verbose=True,
    return_intermediate_steps=True
)

system_prompt = """
你是一个智能数据查询系统，能够理解自然语言查询，根据数据库的 schema 生成准确的 SQL 查询并执行。你需要执行以下步骤：
1. **分析查询需求**：从用户的自然语言查询中识别出涉及的表和字段。
2. **使用图谱进行路径规划**：一旦识别出涉及的表和字段，你需要使用工具`find_join_path`查找这些表的字段的连接关系。具体来说，使用图谱中的外键关系（如 `FOREIGN_KEY_TO`）来推断这些表应该如何连接。
3. **获取字段解释**：在生成 SQL 查询之前，使用工具`retrieve_field_docs` 获取表中涉及字段的详细解释。这一步非常重要，确保你理解每个字段的含义。不要直接猜测字段含义，必须根据字段文档内容来判断。在理解所有字段含义后，思考是否要补充生成SQL所需要的字段。
4. **生成 SQL 查询**：结合路径规划的信息和字段说明，生成一个 sqlserver 支持的有效 SQL 查询。
5. **执行 SQL 查询**：生成的 SQL 查询将通过工具`execute_sql` 执行，并返回查询结果。
6. **过滤查询结果**：在最后一次执行SQL查询得到输出结果后，必须使用工具`retrieve_rules_docs`获取过滤规则，过滤输出结果，并将过滤后的数据作为最终结果输出。
### 工具 ###
- **retrieve_field_docs**：获取字段的详细解释，必须在生成 SQL 之前调用。
- **find_join_path**：根据两个列名返回它们之间的连接路径，帮助确定表之间的关系。
- **execute_sql**：接受一个 SQL 语句并执行，返回执行结果。
- **retrieve_rules_docs**：根据用户输入的自然语言返回相关数据规则，用于过滤sql查询结果。

### 上下文信息 ###
- 使用 **数据库 schema** 来识别涉及的表和字段。
- 使用 **历史查询和结果** 来帮助理解用户的意图。如果用户提到“上一个查询”或“刚才的结果”，请结合这些历史信息来生成 SQL。
### 重要要求 ###
1. **先获取表和字段信息**：你需要先识别查询中涉及的表和字段。可以从上下文中推测查询需求，或者直接从查询中提取出需要的表和字段。
2. **图谱推理**：通过`find_join_path`计算表和字段之间的连接关系。
3. **字段解释**：通过 `retrieve_field_docs` 获取字段的具体意义，避免误解字段的含义。不要直接猜测字段含义，必须根据字段文档内容来判断。在理解所有字段含义后，思考是否要补充生成SQL所需要的字段。
4. **生成SQL语句**：基于所有信息，生成符合查询需求的 SQL 语句。
5. **执行SQL语句**：通过`execute_sql`执行SQL语句并返回数据。无论何时你草拟了 SQL，都必须调用工具 execute_sql 执行该 SQL。不得凭空给出查询结果。给出最终答案前，至少完成一次 execute_sql。
"""

user_prompt_continue = """
{history}

我的需求是：{input}
"""


class ConversationMemory:
    def __init__(self):
        self.schema_info = ""
        self.query_reports = []

    def set_schema(self, schema: str):
        """设置数据库表结构"""
        self.schema_info = schema

    def extract_report_content(self, agent_response: str) -> str:
        """从agent回复中提取查询结果内容"""
        return agent_response

    def add_query_result(self, user_query: str, result_content: str):
        """添加查询和结果内容"""
        self.query_reports.append({"query": user_query, "report": result_content})

    def get_history_string(self) -> str:
        """获取格式化的历史信息"""
        history_str = ""
        if self.schema_info:
            history_str += "### 数据库表结构 ###\n" + self.schema_info + "\n\n"
        if self.query_reports:
            history_str += "### 历史查询和结果 ###\n"
            for i, item in enumerate(self.query_reports, 1):
                history_str += f"查询{i}: {item['query']}\n查询结果:\n{item['report']}\n\n"
        return history_str

    def clear(self):
        """清空历史记录和数据库结构"""
        self.schema_info = ""
        self.query_reports = []

    def get_query_results_only(self) -> str:
        """获取所有查询结果（不包括表结构）"""
        if not self.query_reports:
            return "暂无查询结果"
        result_lines = []
        for i, item in enumerate(self.query_reports, 1):
            result_lines.append(f"查询{i}: {item['query']}")
            result_lines.append(f"查询结果:\n{item['report']}")
            result_lines.append("\n" + "=" * 50 + "\n")
        return '\n'.join(result_lines)

    def get_last_n_exchanges(self, n: int = 3) -> str:
        """获取最近n次查询和结果"""
        history_str = ""
        if self.schema_info:
            history_str += "### 数据库表结构 ###\n" + self.schema_info + "\n\n"
        if self.query_reports:
            recent = self.query_reports[-n:]
            history_str += "### 最近的查询和结果 ###\n"
            for i, item in enumerate(recent, 1):
                history_str += f"查询{len(self.query_reports) - len(recent) + i}: {item['query']}\n查询结果:\n{item['report']}\n\n"
        return history_str

# 全局记忆实例
conversation_memory = ConversationMemory()


def invoke(msg: str, use_full_history: bool = True, max_history: int = 5):
    """
      执行查询
      Args:
          msg: 用户查询需求
          use_full_history: 是否使用完整历史，False则只使用最近几轮
          max_history: 最大历史轮数
      """
    _ensure_initialized()
    # 获取历史记录（包含表结构和历史查询）
    if use_full_history:
        history = conversation_memory.get_history_string()
    else:
        history = conversation_memory.get_last_n_exchanges(max_history)

    # 构建隐藏上下文（平台级注入）
    hidden_ctx = build_hidden_system_context(
        timezone="Asia/Shanghai",
        extra_notes=None,  # 你也可以在这里放部署环境、租户ID等运行态信息
    )

    # 使用统一的prompt格式
    prompt = ChatPromptTemplate.from_messages([
        ("system", hidden_ctx),         # 隐式注入时区
        ("system", system_prompt),
        ("human", user_prompt_continue)
    ]).invoke({"input": msg, "history": history})

    # 提取并保存查询和结果内容
    result = agent.invoke(prompt)
    # 打印 Agent 调用过程
    print("中间调用步骤 Trace:")
    for action, observation in result.get("intermediate_steps", []):
        print(f"[TOOL 调用] {action.tool}")
        print(f"输入: {action.tool_input}")
        print(f"输出: {observation}")
        print("-" * 40)

        # 打印最终输出，方便调试
    print("\n[最终输出]:")
    print(result['output'])
    print("=" * 50)

    result_content = conversation_memory.extract_report_content(result['output'])
    conversation_memory.add_query_result(msg, result_content)
    return result['output']



if __name__ == "__main__":
    print("=== NL2SQL ===")
    print("正在预加载数据库结构...")

    try:
        # 只从缓存载入；若缓存不存在会抛错，提示你先跑 prewarm_script
        schema_info = get_schema()
        conversation_memory.set_schema(schema_info)
        __AGENT_INITIALIZED = True
        print("数据库结构加载完成")
         # ===== 启动时直接显示数据库结构（长文本自动截断） =====
        SCHEMA_EAGER_MAX_CHARS = 20000  # 可按需调大/调小
        print("\n------ 数据库结构（来自 schema_cache）------")
        if len(schema_info) <= SCHEMA_EAGER_MAX_CHARS:
            print(schema_info)
        else:
            print(schema_info[:SCHEMA_EAGER_MAX_CHARS] + "\n...（已截断，输入命令 'schema' 查看完整表结构）")
            print("-" * 60 + "\n")
    except Exception as e:
        print(f"数据库结构加载失败: {e}")
        exit()

    print("输入 'exit' 退出，输入 'clear' 清空历史记录，输入 'history' 查看历史信息")
    print("数据库结构已预加载，直接返回查询结果\n")

    while True:
        user_input = input("请输入你的查询需求：").strip()

        if user_input.lower() == 'exit':
            print("退出对话")
            break
        elif user_input.lower() == 'clear':
            conversation_memory.clear()
            try:
                # 如果清空了历史记录，可以重新加载数据库结构
                # 清空后重新加载（仍然只读缓存）
                schema_info = get_schema()
                conversation_memory.set_schema(schema_info)
                print("历史记录已清空，数据库结构已重新加载")
            except Exception as e:
                print(f"清空历史记录成功，但重新加载数据库结构失败: {e}")
            continue
        elif user_input.lower() == 'history':
            # 显示查询历史
            history = conversation_memory.get_history_string()
            print(history if history else "暂无历史信息")
            continue
        elif not user_input:
            print("请输入有效的查询需求")
            continue

        print("正在处理中，请稍等...")

        try:
            result = invoke(user_input)
            print("\n查询结果：")
            print(result)
            print("\n" + "=" * 50 + "\n")
        except Exception as e:
            print(f"处理过程中出现错误：{e}\n{'=' * 50}\n")
