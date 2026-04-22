# Report-Agent —  基于 NL2SQL 的报告生成智能体 

## 一、项目简介

本项目面向水文局业务场景，构建了一个基于 **NL2SQL** 的报告生成智能体。系统能够理解用户提出的水情报告需求，自动完成意图识别、模板匹配、查询规划、数据获取与报告写作，将传统依赖人工整理的数据查询与文字编写流程转化为自动化、可追溯的智能生成流程，提升水文业务报告编制效率与规范性。 

其中，项目在数据库 schema 的组织与表达上参考了阿里析言的相关设计思路，以增强查询规划和数据检索过程中的结构化约束能力。 

## 二、系统架构

```
用户自然语言报告需求
    |
    v
节点1：意图识别 + 关键信息提取
    |
    |-- 判断请求属于 query / report / other
    |-- 提取 report_type / time / region
    v
节点2：报告需求 -> 自然语言查询规划
    |
    |-- 读取报告模板 templates/
    |-- 读取数据库 schema
    |-- 结合用户需求 + 模板 + schema
    |-- 生成一组面向 NL2SQL 的自然语言查询语句
    v
节点3：查询调度
    |
    |-- 从 plan 中逐条取出待执行查询
    |-- 控制后续进入 NL2SQL 或最终写作节点
    v
节点4：NL2SQL 执行
    |
    |-- 接收自然语言查询
    |-- 调用 NL2SQL的服务接口
    |-- 进入 NL2SQL执行查询代理
    |   |
    |   |-- 加载数据库结构schema
    |   |-- 将 schema 注入会话记忆
    |   |-- 使用 qwen3-max 做工具调用与SQL生成
    |   |-- tools:execute_sql：执行 SQL
    |   |-- tools:retrieve_field_docs：检索字段说明
    |   |-- tools:retrieve_rules_docs：检索业务规则
    |   └-- tools:find_join_path：基于知识图谱查找表关联路径
    |   
    |-- 输出查询结果
    v
节点5：查询结果检查
    |
    |-- 判断结果状态：ok / empty / error
    |-- 保留原始结果
    |-- 记录 warnings / errors / evidence_summary
    v
节点6：报告生成
    |
    |-- 汇总查询结果、提纲、模板信息
    |-- 生成报告正文
    |-- 追加查询证据、风险提示、失败信息
    v
最终输出：水情报告 / 查询结果
```

## 三、代码结构

```
report_agent/
├── graph.py                 # 主流程图定义与 WebSocket 执行入口
├── node.py                  # 节点1~节点6的核心实现
├── template_planner.py      # 节点2：模板读取、请求提取、查询规划
├── report_writer.py         # 节点6：报告正文生成
├── helper.py                # 通用工具函数、路由逻辑、附录构建
├── state.py                 # LangGraph 共享状态定义
├── readme.md                # 本文档
├── .env                     # 环境配置
├── templates/               # 报告模板目录
│   └── report.md            # 日报/周报/月报模板
├── test/                    # 测试脚本目录
└── NL2SQL/                  # NL2SQL 核心查询能力层
    ├── agent_mod.py         # FastAPI 接口，对外提供 /nl2sql 服务
    ├── agent.py             # NL2SQL Agent 主逻辑：自然语言 -> SQL -> 查询结果
    ├── get_schema_cache.py  # schema 缓存生成脚本
    ├── runtime_context.py   # 运行时上下文
    ├── schema_cache/        # schema 缓存层
    │   ├── loader.py        # schema 缓存读取
    │   └── schema.json      # 数据库 schema 缓存文件
    ├── schema_engine/       # schema 组织与结构表达
    │   ├── m_schema.py      # MSchema 结构定义
    │   ├── schema_engine.py # schema 解析与组织
    │   ├── utils.py         # schema 工具函数
    │   └── xiyan.py         # schema 表达相关代码
    ├── rag/                 # 字段说明、规则文档等检索增强
    │   ├── loader.py        # 文档分块
    │   ├── retriever.py     # 检索器
    │   └── embedder.py      # 向量化组件
    │  
    ├── knowledge_graph/     # 表关系图与 join 路径查找
    │   ├── graph_builder.py # 表关系图构建脚本
    │   ├── graph_query.py   # join 路径查询
    │   └── table_relations.json
    ├── config/
    │   └── settings.py      # 配置文件
    └── docs/
        └── schema_doc.md    # schema字段说明文档
```

## 四、关键设计

### 4.1 基于状态图的主流程编排

项目主流程使用 **LangGraph** 组织为 6 个明确节点：

1. 意图分析
2. 模板选择与查询拆解
3. 查询调度
4. `NL2SQL` 执行
5. 结果检查
6. 最终输出

这种设计把“理解需求”“规划查询”“执行查询”“检查结果”“生成报告”拆成了职责单一的阶段，带来的好处是：

- 各节点输入输出边界清晰，便于单独测试和排查。
- `query` 与 `report` 两类请求可以复用同一条主流程，只在节点内部做分支。
- 状态统一保存在 `GraphState` 中，能够在流程末尾生成完整的可追溯输出。

### 4.2 查询与报告双模式统一处理

系统支持两类核心请求：

- **直接查询**：例如“查询昨天各站点最大雨量”。
- **报告生成**：例如“生成今天的水情日报”。

在节点 1 中，系统会先判断请求属于 `query`、`report` 或 `other`。其中：

- `query` 模式会直接生成一条待执行查询，进入查询流程。
- `report` 模式会继续做模板选择、提纲生成和查询规划。
- `other` 模式会提前结束，避免无意义地进入后续查询链路。

这种统一入口设计减少了重复实现，也避免了“先判断请求类型，再切换完全不同子系统”的维护成本。

### 4.3 NL2SQL 智能体执行链路

本项目最核心的部分是 `NL2SQL` 子系统。该系统基于 **LangChain** 框架实现，并未将自然语言直接交由大模型 “生成一条 `SQL`”，而是采用 `ReAct`的推理范式，把 SQL 生成过程拆成“理解需求 -> 获取约束 -> 路径规划 -> 执行查询 -> 规则过滤”几个阶段。也就是说，`LLM` 先基于当前问题进行推理，再按需调用工具获取外部信息，最后在观察工具返回结果后继续推进后续步骤。

整体执行链路如下：

1. 分析自然语言查询需求，识别涉及的指标、表和字段。
2. 调用 `retrieve_field_docs` 检索字段说明，避免误解字段语义。
3. 调用 `find_join_path` 查找表间 `join` 路径，确定多表连接关系。
4. 生成面向 `SQL Server` 的 `SQL` 语句。
5. 调用 `execute_sql` 执行 `SQL`，并返回结果。
6. 调用 `retrieve_rules_docs` 检索业务规则，对结果口径做补充约束。

这一设计的重点在于：`LLM` 主要负责 `ReAct` 过程中的推理与调度，真正和数据库、字段文档、规则知识、关系图谱打交道的动作全部通过工具完成。这样既保留了大模型在复杂查询分解和 `SQL` 规划上的灵活性，也尽量减少了“模型凭空猜字段、猜表关系、猜业务规则”的问题。

### 4.4 Schema、RAG 与知识图谱协同约束

为了提高 `NL2SQL` 的正确率，项目在 `SQL` 生成前引入了三层约束信息：

#### 1. Schema 解析与缓存

- `SchemaEngine` 会从数据库中提取表结构、字段信息和外键关系，并组织成统一的 `MSchema` 表示。
- `get_schema_cache.py` 会把解析结果预热到 `schema_cache/schema.json` 中，供运行时直接加载。
- 这样做可以避免在每次查询时重复扫描数据库元数据，并为 LLM 提供更快、更稳定的结构化 schema 输入。

#### 2. 字段说明与规则检索

- `retrieve_field_docs` 基于 `docs/schema_doc.md` 构建的 `Chroma` 向量库检索字段说明。
- 这一步的目标是解决“字段名看起来像一个意思，实际业务含义却不同”的问题。
- `retrieve_rules_docs` 则从规则知识库中检索业务规则、统计口径和结果过滤依据。

#### 3. Neo4j 路径规划

- `find_join_path` 会在 Neo4j 图数据库中寻找两列之间的最短路径。
- 图谱节点由 `Table` 和 `Column` 组成，关系包括 `HAS_COLUMN` 和 `FOREIGN_KEY_TO`。
- 图谱关系不仅包含数据库原生外键，也支持通过 `table_relations.json` 补充人工维护的外键关系。

这三部分一起作用，形成了“数据库结构约束 + 字段语义约束 + 表关系约束”的协同机制，是本项目 `NL2SQL` 能够稳定生成可执行 SQL 的关键。

### 4.5 会话记忆与查询稳定性

`NL2SQL` 智能体内部维护了一套轻量的会话记忆：

- 静态部分是数据库 schema 信息。
- 动态部分是历史查询与查询结果。

这种设计带来两个直接收益：

- 连续追问时，模型可以利用前面的查询上下文理解“刚才那个结果”“和上一次相比”等表达。
- schema 只需要在初始化时装载一次，避免重复拼接，降低上下文噪声。

同时，系统还做了几项稳定性处理：

- SQL 执行结果会做长度截断，避免工具返回过长内容撑爆上下文。（目前为截断而非压缩，后续可优化）
- 查询结果检查节点会把结果分类为 `ok / empty / error`，把失败和空结果显式沉淀为 `warnings` 与 `errors`。
- 意图分析和结果检查都提供了本地回退规则，在模型异常时仍可继续运行。

### 4.6 模板规划与最终报告生成

相较于 `NL2SQL`，报告生成部分只做两件事：

1. 将报告需求拆成一组自然语言查询任务。
2. 基于查询结果、提纲、模板和证据摘要生成最终报告。

这里的设计重点不是让模型直接“自由写作”，而是让报告生成严格建立在 `NL2SQL` 已经拿到的数据证据之上。最终输出还会追加查询证据、风险提示和失败信息，保证报告结果可追溯、可解释。

## 五、环境依赖

### 5.1 Python 依赖

```bash
pip install -r requirements.txt
```

### 5.2 环境变量（.env）

| 变量名 | 说明 |
| --- | --- |
| `DB_URI` | SQL Server 连接串，用于 NL2SQL 查询数据库 |
| `DB_SCHEMA` | 数据库默认 schema 名 |
| `DASHSCOPE_APIKEY` | 阿里百炼 API Key，用于调用 Qwen 模型 |
| `BASE_URL` | DashScope 兼容接口地址 |
| `NL2SQL_MODEL` | NL2SQL 模块使用的模型名称 |
| `MODEL` | 主流程使用的模型名称 |
| `NL2SQL_URL` | NL2SQL 服务接口地址 |
| `CHROMA_DB_DIR` | 数据库字段说明的Chroma 向量库目录 |
| `RULES_CHROMA_DB_DIR` | 规则知识库的 Chroma 向量库目录 |
| `HF_MODEL_DIR` | 本地 HuggingFace 向量模型目录 |
| `NEO4J_URI` | Neo4j 图数据库连接地址 |
| `NEO4J_USER` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | Neo4j 密码 |
| `DB_HOST` | MySQL 主机地址，用于存储业务规则 |
| `DB_PORT` | MySQL 端口 |
| `DB_USER` | MySQL 用户名 |
| `DB_PASSWORD` | MySQL 密码 |
| `DB_NAME` | MySQL 数据库名 |

### 5.3 模型使用

| 模型           | 用途         | 说明                                           |
| -------------- | ------------ | ---------------------------------------------- |
| `qwen3-max`    | NL2SQL 模型  | 用于该服务ReAct 循环中的推理与决策             |
| `qwen-plus`    | 主流程模型   | 用于意图分析、模板规划、查询结果检查和报告生成 |
| `bge-small-zh` | 向量检索模型 | 用于 RAG                                       |

所有LLM模型均通过阿里云百炼 DashScope 接口调用，未进行任何微调。

## 六、复现步骤

### 6.1 环境准备

1. 安装软件Neo4j Desktop 2，创建一个图数据库

2. 配置 `.env` 文件与`/NL2SQL/config/settings.py下的INCLUDE_TABLES` （可选，数据库中需要用到的表）

3. 安装依赖：`pip install -r requirements.txt`

4. `templates/`下配置报告模板

5. `docs/schema_doc.md`中补充表字段说明，格式参数示例：

   ```
   ### 表名：dbo.ST_PPTN_R
   降水量表用于存储时段降水量和日降水量。
   表结构各字段描述如下：
   1. STCD (测站编码)：测站编码具有唯一性，由数字和大写字母组成的 8 位字符串。
   2. TM (时间)：降水量值的截止时间。
   3. DRP (时段降水量)：表示指定时段内的降水量，计量单位为 mm。
   4. INTV (时段长)：描述测站所报时段降水量的统计时段长度。数据存储的格式是 HH.NN，其中 HH 为小时数，取值为 00～23；NN 为分钟数，取值为 01～59。当降水历时为整小时数时，可只列小时数。
   5. PDR (降水历时)：描述指定时段的实际降雨时间。数据存储的格式是 HH.NN。日降水量：1d 累计的降水量，计量单位为 mm。
   6. WTH (天气状况）：时间字段截至时刻的天气状况，用代码表示。5=“雪”，6=”雨夹雪“，7=”雨“，8=”阴“，9=”晴“
   7. GGMD (观测方式)：信息观测或采集的方式，“0”或“空值”表示自动监测，“1”表示人工监测。
   ```

6. 运行`run_waterknow.py`建立mysql规则数据库

7. 运行`rag/embedder.py`建立向量库

8. 打开`neo4j Desktop 2` 并运行创建好的图数据库，运行`graph_builder.py`构建知识图谱（可选：补充`table_relations.json`中的外键关系）

9. 运行`get_schema_cache.py`缓存数据库结构

### 6.2 本地调试

```bash
# 进入项目目录
cd D:\Work\report_agent

# 1. 启动 NL2SQL 服务
python -m uvicorn NL2SQL.agent_mod:app --host 0.0.0.0 --port 8001

# 2. 检查 NL2SQL 服务健康状态
curl http://127.0.0.1:8001/health

# 3. 调试 NL2SQL 单条查询
curl -X POST http://127.0.0.1:8001/nl2sql \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"查询昨天各站点最大雨量\"}"

# 4. 启动主流程 WebSocket 服务
python graph.py
```

启动后默认监听：

- NL2SQL 服务：`http://127.0.0.1:8001`
- WebSocket 主流程：`ws://localhost:8080`

如果只想验证 NL2SQL 子模块，执行前 3 步即可。

如果要联调整个报告生成流程，可连接 `ws://localhost:8080` 并发送一条纯文本问题，例如：

```text
生成今天的水情日报
```

## 七、API 接口

本项目当前包含两类接口：

1. `NL2SQL` 子服务接口：基于 `FastAPI`，对外提供自然语言查询能力。
2. 主流程接口：基于 `WebSocket`，负责串联意图识别、模板规划、NL2SQL 查询、结果检查与最终报告生成。

### 7.1 NL2SQL 子服务

服务默认地址：`http://127.0.0.1:8001`

#### GET /health

- **用途**：检查 `NL2SQL` 服务是否正常启动。
- **请求示例**：

```bash
curl http://127.0.0.1:8001/health
```

- **返回示例**：

```json
{"status":"ok"}
```

#### POST /nl2sql

- **用途**：将单条自然语言查询交给 `NL2SQL` Agent 执行。
- **请求体**：

```json
{"query":"查询昨天各站点最大雨量"}
```

- **返回体**：

```json
{"output":"...查询结果文本..."}
```

- **请求示例**：

```bash
curl -X POST http://127.0.0.1:8001/nl2sql \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"查询昨天各站点最大雨量\"}"
```

### 7.2 主流程 WebSocket 接口

服务默认地址：`ws://localhost:8080`

- **用途**：接收一条用户问题，执行完整主流程，并持续回传阶段状态和最终结果。
- **输入格式**：客户端直接发送一条纯文本消息，例如：

```text
生成今天的水情日报
```

- **事件类型**：
  `start`：收到用户输入，准备开始执行。
  `stage`：某个节点开始或结束，包含轻量状态摘要。
  `final`：流程结束，返回最终报告和辅助信息。
  `error`：执行出错。

- **`stage` 事件示例**：

```json
{
  "type": "stage",
  "stage": "nl2sql",
  "status": "completed",
  "state": {
    "iterations": 1,
    "meaning": "query",
    "template_name": null,
    "report_type": null,
    "time": "2026-03-22",
    "region": null,
    "query_tasks_count": 0,
    "current_query": null,
    "remaining_queries": 0,
    "results_count": 1,
    "warnings_count": 0,
    "errors_count": 0,
    "done": false
  }
}
```

- **`final` 事件示例**：

```json
{
  "type": "final",
  "final_report": "...最终报告或查询结果...",
  "state": {
    "iterations": 2,
    "meaning": "report",
    "template_name": "日报",
    "report_type": "日报",
    "time": "2026-03-23",
    "region": "四川省",
    "query_tasks_count": 4,
    "current_query": null,
    "remaining_queries": 0,
    "results_count": 4,
    "warnings_count": 0,
    "errors_count": 0,
    "done": true
  },
  "warnings": [],
  "errors": [],
  "evidence_summary": [],
  "outline": []
}
```

## 八、总结

本项目面向水文业务场景，构建了一套从自然语言需求到数据查询、再到报告生成的完整链路。其中，`NL2SQL` 子系统是核心能力：通过 `schema` 解析、字段说明检索、业务规则检索和 路径规划等机制，为大模型生成 SQL 提供了多层约束，降低了直接生成 SQL 时常见的字段误解、表关联错误和业务口径偏差问题。

在此基础上，系统进一步将报告生成拆分为“模板规划 + 查询执行 + 结果检查 + 约束式写作”几个阶段，使最终输出不仅能够生成文本，还能够保留查询证据、风险提示和失败信息，具备较好的可追溯性、可解释性和工程可用性。整体上，本项目实现了从“能查”到“查得对、查得稳”、再到“能基于查询结果生成报告”的一体化能力。

需要说明的是，当前项目所依赖的 Agent 实现框架整体上仍基于较早期的`LangGraph/LangChain` **0.3** 版本生态，虽然已经能够满足当前功能落地，但在工具编排能力、上下文管理、可观测性、模块复用和开发范式上，与目前最新的 Agent 开发环境相比仍有一定差距。后续可进一步借鉴 最新的 Agent 开发思路，对系统进行升级优化，从而提升系统的可维护性、扩展性以及复杂场景下的开发效率。
## 九、License

本项目基于 [MIT License](LICENSE) 开源。

