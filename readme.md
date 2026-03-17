# 环境配置

**win环境：**

1. 创建一个新环境，安装python=3.10

```
conda create -n env_name python=3.10
```

2. 安装pytorch

```
pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu118
```

3. 找到requirements.txt，安装其余依赖

```
pip install -r requirements.txt
```

4. 安装软件Neo4j Desktop 2，创建一个图数据库



# agent配置

1. 配置.env

```
DB_URI=                                              #业务数据库url
DASHSCOPE_APIKEY=                                    #llm-key
#向量库相关
CHROMA_DB_DIR=D:/Work/NL2SQL/rag/chroma_db           #表字段解释向量库
LTM_CHROMA_DB_DIR=D:/Work/NL2SQL/rag/chroma_ltm      #智能体长期记忆向量库，非必须
RULES_CHROMA_DB_DIR=D:/Work/NL2SQL/rag/chroma_rules  #业务规则向量库
HF_MODEL_DIR=D:/Work/NL2SQL/hf_models/bge-small-zh   #向量化模型本地地址
#NEO4J相关
NEO4J_URI=bolt://127.0.0.1:7687                      #neo4j_url,默认bolt://127.0.0.1:7687  
NEO4J_USER=                                          #图数据库名称
NEO4J_PASSWORD=                                      #密码
# mysql规则数据库相关
DB_HOST=localhost                                    #地址
DB_PORT=3306                                         #端口
DB_USER=root                                         #用户
DB_PASSWORD=                                         #密码
DB_NAME=waterknow                                    #数据库名
```

2. docs/schema_doc.md中补充表字段解释，格式参数示例

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

3. 运行run_waterknow.py建立mysql规则数据库

4. 运行rag/embedder.py建立向量库
5. 打开neo4j Desktop 2 并运行创建好的图数据库，补充table_relations.json中的外键关系并运行graph_builder.py构建知识图谱
6. 运行get_schema_cache.py缓存数据库结构

# agent使用

完成上述配置后，每次使用NL2SQL  agent只需在确保图数据库运行的情况下运行agent.py

