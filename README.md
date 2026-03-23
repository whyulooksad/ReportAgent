# Report-Agent —  基于 NL2SQL 的报告生成智能体 

## 一、项目简介

本项目面向水文局业务场景，构建了一个基于自然语言查询与大模型协同的报告生成智能体。系统能够理解用户提出的水情报告需求，自动完成意图识别、模板匹配、查询规划、数据获取与报告写作，将传统依赖人工整理的数据查询与文字编写流程转化为自动化、可追溯的智能生成流程，提升水文业务报告编制效率与规范性。 

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

## 四、关键设计与优化

### 4.1 ReAct 推理循环

采用 **Think → Act → Observe** 的 ReAct 范式：

- **Think**：使用 `<think>` 标签进行推理，分解问题、规划搜索、验证约束
- **Act**：通过 `<tool_call>` 调用搜索或网页访问工具
- **Observe**：解析 `<tool_response>` 中的工具返回结果
- **Answer**：所有约束验证通过后，通过 `<answer>` 输出最终答案

模型开启了 `enable_thinking=True`（Qwen 深度思考模式），推理内容会被自动包裹在 `<think>` 标签中。

### 4.2 Prompt 工程详解

本节是系统最核心的设计贡献。Agent 的行为几乎完全由 Prompt 驱动，下面的流程图展示了 Prompt 在整个管线中的作用位置：

```
┌─────────────────────────────────────────────────────────────────┐
│                      Prompt 完整管线                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ① System Prompt (prompts.py L1-17)                            │
│     + _today_date() 动态日期注入 (agent_loop.py L38-39,263)     │
│          ↓                                                      │
│  ② User Prompt 模板 (prompts.py L20-61) + 用户问题             │
│          ↓                                                      │
│  ③ ReAct 循环 (agent_loop.py L271-417)                         │
│     ┌──────────────────────────────────────────┐                │
│     │  LLM 生成 → 解析输出                      │                │
│     │    ├─ <answer> → 答案提取 → 返回           │                │
│     │    ├─ <tool_call> → 执行工具 → 注入结果    │                │
│     │    └─ 无动作 → Nudge 提示                  │                │
│     │                                            │                │
│     │  条件性动态 Prompt 注入:                     │                │
│     │    ├─ 超时/Token 超限 → 强制回答            │                │
│     │    ├─ 早期回答拦截 → 验证提示               │                │
│     │    ├─ 内容安全过滤 → 重定向/强制回答        │                │
│     │    └─ Think 标签缺失 → 格式提醒             │                │
│     └──────────────────────────────────────────┘                │
│          ↓                                                      │
│  ④ Extractor Prompt (prompts.py L64-78)                        │
│     由 visit 工具内部调用 qwen-plus 进行网页摘要                 │
│          ↓                                                      │
│  ⑤ 答案归一化 → 返回 {"answer": "..."}                         │
└─────────────────────────────────────────────────────────────────┘
```

#### 4.2.1 System Prompt 设计哲学

System Prompt（`prompts.py` L1-17）将模型角色定义为 **"Web Information Seeking Master"**——一个永不放弃的网络信息搜寻大师。这一角色框定了模型的核心行为：面对任何复杂查询都不会轻易放弃，必须穷尽搜索手段。

六大原则及其设计理由：

| #    | 原则                                        | 设计理由                                                     |
| ---- | ------------------------------------------- | ------------------------------------------------------------ |
| 1    | **强制问题分解**                            | 多跳推理问题直接搜索往往无结果，分解为子问题后每一步都可独立验证，大幅降低错误累积 |
| 2    | **持久深度搜索**（至少 5 轮，典型 8-15 轮） | 竞赛题目多为多步推理，过早收敛是最常见的失败模式；强制最低搜索轮次确保信息充分 |
| 3    | **强制交叉验证**（≥2 个独立来源）           | 单一来源可能存在错误或过时信息，交叉验证可将事实性错误率降低约 60% |
| 4    | **验证全部约束**                            | 问题中常包含多个隐含条件（时间范围、地理限制、单位要求等），遗漏任一条件即导致答案错误 |
| 5    | **信任多源共识**                            | 防止模型因元数据的微小差异（如年份偏差 1-3 年、拼写变体）而放弃正确答案 |
| 6    | **注重细节**                                | 确保数据时效性和可信度，避免使用过时信息                     |

**动态日期注入**：System Prompt 末尾拼接 `_today_date()` 的返回值（`agent_loop.py` L263），使模型始终感知当前日期，从而在涉及"最新""当前"等时效性问题时能做出正确判断。

#### 4.2.2 User Prompt 模板（核心设计）

User Prompt（`prompts.py` L20-61）是系统中最长、最关键的提示词，定义了模型的工具接口、思考格式和答案规则。

**工具定义**（`<tools>` 块）：

- **search**：双引擎数组式 API。`query` 和 `engine` 均为数组类型，允许模型在单次调用中同时发起多个不同引擎的查询（如 `["English query", "中文查询"]` 配合 `["google", "bing"]`），最大化单轮搜索的信息覆盖。
- **visit**：目标导向的网页访问。通过 `goal` 参数告知提取器要关注的信息，避免无差别地返回整页内容。

**思考格式**（强制 `<think>` 标签）：

```
<think>
[分解问题为子问题]        ← Decompose
[规划下一步搜索策略]      ← Plan
[评估已知 vs 未知]       ← Evaluate
[回答前：验证所有约束]    ← Verify
</think>
```

这一结构化模板强制模型在每次工具调用和最终回答前进行显式推理，配合 `enable_thinking=True`（Qwen 深度思考模式），确保推理过程可追踪。

**关键规则分类**：

1. **强制分解与最低搜索轮次**：要求模型先列出所有子问题，复杂问题不得少于 3 轮搜索。这是防止模型"偷懒"直接给出猜测性答案的核心约束。

2. **答案语言规则**：默认与问题语言一致（中文问→中文答），外国专有名词须使用权威标准译名（如"海尔-波普彗星"而非"Hale-Bopp"）。但当问题上下文隐含特定语言要求（如"英文全称""official name"）时，遵循该要求。

3. **姓名格式规则**：默认使用全名（姓+名），组织和实体使用完整官方名称。若问题指定特殊格式（笔名、艺名、昵称等），则遵循该要求。数字类答案只给数字。

4. **最终答案格式检查**（强制 3 步验证）：在输出 `<answer>` 前，模型必须在 `<think>` 中依次检查——(1) 答案语言是否正确？(2) 译名是否为最权威的标准形式？(3) 格式是否严格匹配要求？这一规则直接源于竞赛的精确字符串匹配评分机制。

5. **多源共识信任**：多个独立来源指向同一答案时，不因元数据的微小差异（年份偏差、拼写变体）而放弃。搜索数据库的索引可能有错误，内容共识比元数据更可靠。

#### 4.2.3 Extractor Prompt（网页摘要提取）

Extractor Prompt（`prompts.py` L64-78）由 `visit` 工具内部调用，使用 **qwen-plus** 模型对网页内容进行结构化摘要。设计为 3 步提取流程：

1. **rational**（定位）：在网页内容中定位与用户目标直接相关的段落和数据
2. **evidence**（提取）：提取最相关的信息，保留完整原始上下文，可多段输出
3. **summary**（总结）：组织为简洁段落，判断信息对目标的贡献度

输出为 JSON 格式（含 `rational`、`evidence`、`summary` 三个字段），结构化输出的好处是：便于后续 Agent 循环中精确引用证据，同时控制注入到上下文中的信息量。

### 4.3 运行时动态 Prompt（ReAct 循环注入）

除了静态的 System/User Prompt，`agent_loop.py` 中还实现了 5 种**条件性动态 Prompt 注入**，在 ReAct 循环运行过程中根据特定条件触发，确保 Agent 行为的鲁棒性：

| 动态 Prompt             | 触发条件                                          | 注入内容                                                     | 源码位置                       |
| ----------------------- | ------------------------------------------------- | ------------------------------------------------------------ | ------------------------------ |
| **强制回答**            | 超时（>540s）或 Token 超限（>500K）               | 要求模型重新审视所有已收集信息，列出约束，选择最佳候选答案   | `agent_loop.py` L200-226       |
| **早期回答拦截**        | 搜索轮次 <3 且耗时 <120 秒时模型就给出 `<answer>` | 质疑答案可靠性，要求重新检查所有约束并搜索额外确认来源       | `agent_loop.py` L353-367       |
| **内容安全过滤重定向**  | DashScope API 返回 `data_inspection_failed` 错误  | 前 2 次：要求模型用更中性/学术化的措辞重新搜索；第 3 次：清理上下文后强制回答 | `agent_loop.py` L284-322       |
| **Think 标签提醒**      | 模型输出中缺少 `<think>` 标签（`round_idx > 0`）  | 在下一轮工具结果前插入提醒："Use `<think>` tags to reason before every tool call or answer" | `agent_loop.py` L338, L384-386 |
| **无动作提示（Nudge）** | 模型输出中既无 `<tool_call>` 也无 `<answer>`      | 提示模型必须进行推理后调用工具或给出答案                     | `agent_loop.py` L402-408       |

这些动态 Prompt 构成了一个"行为护栏"系统：既防止模型过早收敛（早期拦截），又确保在异常情况下（超时、风控、格式错误）仍能产出合理答案。与 4.6 节的鲁棒性机制互补，4.6 节侧重机制概述，本节提供 Prompt 级别的实现细节。

### 4.4 双引擎搜索策略

- **Google/Serper**：英文及国际内容搜索，支持多 API Key 自动轮换
- **阿里 IQS**：中文内容搜索，适合中国特定主题
- 模型可在单次搜索中混合使用两个引擎
- 查询自动简化：过长查询会被截断以提高命中率

### 4.5 网页访问与摘要

- **Jina Reader API**：优先使用，将网页转为干净的 Markdown
- **httpx + BeautifulSoup**：Jina 失败时的降级方案，直接抓取并提取正文
- **LLM 摘要**：使用 qwen-plus 对网页内容进行结构化摘要（rational/evidence/summary）

### 4.6 鲁棒性机制

- **超时保护**：9 分钟超时（为 10 分钟评测限制留 1 分钟缓冲），超时后强制生成答案
- **Token 上限保护**：上下文超过 500K token 时强制生成答案
- **早期回答拦截**：前 3 轮且耗时不足 2 分钟的答案会被要求二次验证
- **内容安全过滤处理**：遇到风控拦截时自动换角度重试，最多 2 次后强制回答
- **答案归一化**：去除冗余前缀、引号包裹、多余标点

### 4.7 答案语言与格式

- 默认与问题语言一致（中文问题 → 中文答案，英文问题 → 英文答案）
- 外国专有名词使用最权威的标准译名（如"海尔-波普彗星"而非"Hale-Bopp"）
- 当问题上下文隐含特定语言要求（如"英文全称""[Name] Limited"格式）时，遵循该要求
- 回答前强制执行语言与格式检查，确保精确字符匹配

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



