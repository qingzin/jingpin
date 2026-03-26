# BOM 零部件语义检索 — Ingestion Pipeline

## 快速开始

### 1. 安装依赖

```powershell
py -3 -m pip install -r requirements.txt
```

### 2. 配置 API Key（两种方式选一）

Windows PowerShell:

```powershell
$env:BGE_API_KEY="your_bearer_token_here"
```

Windows CMD:

```bat
set BGE_API_KEY=your_bearer_token_here
```

更推荐直接走命令行参数，这样不依赖 shell：

```powershell
py -3 ingestion_pipeline.py data\your_file.xlsx --api-key "your_bearer_token_here"
```

### 3. 运行单文件测试

```powershell
# 仅验证结构化写入（不调用 embedding API）
py -3 ingestion_pipeline.py data\your_file.xlsx --no-embed

# 完整流程（含 embedding）
py -3 ingestion_pipeline.py data\your_file.xlsx --api-key "your_bearer_token_here"
```

### 4. 批量处理所有文件

```powershell
py -3 ingestion_pipeline.py --dir data --api-key "your_bearer_token_here"
```

### 5. 运行测试套件（无需真实文件和 API）

```powershell
py -3 test\test_pipeline.py
```

---

## 项目结构

```
20260310jingping_demo/
├── config/
│   └── column_mapping.json      # 列名归一化映射表（157列 → 统一字段名）
├── core/
│   ├── column_normalizer.py     # 列名归一化 + Level 列检测
│   ├── form_detector.py         # 形态A/B识别 + 层级路径重建
│   ├── embedder.py              # BGE-M3 API 客户端 + embedding 文本构建
│   ├── db_duckdb.py             # DuckDB 结构化存储
│   └── db_qdrant.py             # Qdrant 向量存储
├── test/
│   ├── test_pipeline.py         # Pipeline 核心逻辑测试
│   └── test_search_product.py   # 搜索产品核心逻辑测试
├── ingestion_pipeline.py        # 主入口：单文件/批量处理
├── embed_only.py                # 从现有 DuckDB 补做 embedding 并写入 Qdrant
├── search_cli.py                # 命令行交互检索入口
├── streamlit_app.py             # 本地 Streamlit 前端
├── requirements.txt             # Python 依赖清单
├── data/                        # 放置你的 Excel/CSV 文件
└── db/
    ├── bom.duckdb               # 结构化数据库（自动创建）
    └── qdrant_storage/          # 向量索引（自动创建）
```

---

## 表格形态说明

| 形态 | 判断条件 | 名称来源 | 典型列名 |
|------|---------|---------|---------|
| **A** | 无 `零部件名称` 列 | 最深非空 Level 列 | `Part Level 0-8` |
| **B** | 有 `零部件名称` 列 | 直接取该列值 | `零部件名称` + `Part Level 0-8` |

---

## 关键设计点

### 合并单元格自动修复
Excel 合并单元格展开后 Level 列会出现空值，pipeline 自动做前向填充（ffill）：
```
原始：车身系统 | 车门总成 | 零件A
     NaN      | NaN      | 零件B   ← 合并单元格 pandas 读出为 NaN
修复：车身系统 | 车门总成 | 零件A
     车身系统  | 车门总成 | 零件B   ← ffill 后
```

### 层级查询（DuckDB LIST 类型）
```sql
-- 包含"车门总成"的所有零件
SELECT * FROM parts WHERE list_contains(level_array, '车门总成');

-- 第1层是"车身系统"且深度≤4层
SELECT * FROM parts WHERE level_array[1] = '车身系统' AND level_depth <= 4;

-- 第2层是"车门总成"的直接子节点
SELECT * FROM parts WHERE level_array[2] = '车门总成' AND level_depth = 3;
```

### 溯源字段
每行都记录：
- `source_file`：来源文件名
- `source_row`：原始行号
- `part_name_source`：名称来自哪列（`part_name` / `level_2` / `level_3` 等）
- `name_confidence`：`direct`（形态B直接取） / `derived`（形态A推导） / `missing`
- `raw_data`：原始行完整 JSON，零损失兜底

---

## Embedding API

- **Endpoint**: `https://aiservice.byd.com/yicellm-api/v1/embeddings`
- **Model**: `bge-m3`
- **Auth**: `Authorization: Bearer <token>`
- **兼容格式**: OpenAI embeddings API

Embedding 文本格式（仅名词/层级结构）：
```
零件名称 | 别名/类型 | 层级路径 | 系统/位置/结构描述
例：前左门密封条 | 密封条 | 车身系统 > 车门总成 > 前左门 | 车门区域
```

说明：
- `part_number`、`material`、`manufacturer`、`vehicle_model`、重量尺寸等字段不再进入 embedding 文本
- 这些字段更适合做 DuckDB 精准过滤和 Qdrant payload 展示，而不是模糊语义召回

### Qdrant Payload（用于过滤 + 结果展示）

payload 现在会保存更适合工程检索的字段，例如：
- `vehicle_name`：实际车型名，默认取 `source_file`
- `part_name`、`part_number`
- `level_path`、`level_depth`
- `weight_kg`、`length_mm`、`width_mm`、`height_mm`、`thickness_mm`
- `material`、`material_type`、`material_grade`、`surface_treat`、`process`
- `manufacturer`、`location`、`detail`、`part_type`

其中：
- `source_file`：保留原始来源文件名，便于溯源
- `borrowed_vehicle_model`：保留表格内原始 `vehicle_model` 字段，但不再把它当成实际车型

### 推荐检索策略

针对“竞品整车拆解 BOM”这个数据库，工程师的典型需求一般是：
- “找和前门铰链类似的零件，并看看出现在哪些车型”
- “找钢制、带电泳表面处理、厚度 1.2mm 左右的门板件”
- “找前舱区域、重量小于 0.5kg 的支架/卡扣/加强板”

因此推荐的检索流程是：
1. 先用 DuckDB 做所有结构化过滤：材料、表面处理、重量范围、尺寸范围、层级节点等
2. 如果有语义描述，再把 DuckDB 过滤后的候选集交给 Qdrant 做语义召回
3. 返回零部件明细，并额外汇总命中的 `source_file`，用于继续定位点云文件或拆解图片

补充说明：
- 如果用户的语义词本身就是明确零部件目标，例如“引擎盖”，系统会先在 DuckDB 中把“零部件名称命中”或“末级层级命中”的候选全找出来；只要能直接锁定，就直接返回这批结果，不再受 `candidate_limit` 截断
- 如果结构化过滤命中量不大，系统会把全部过滤结果交给 Qdrant 做语义排序，而不是机械地截前 200 条
- 如果过滤结果很多，但又不是明确目标件，系统会先按零部件名、末级层级和层级词面线索做一轮 DuckDB 预筛，再交给 Qdrant

这样做的好处：
- 检索更快：先缩候选集，再做向量搜索
- 结果更准：过滤属性不会污染向量空间
- 展示更完整：命中后仍然能看到尺寸、材料、表面处理等工程属性
- 更符合使用场景：先找零部件，再看它出现在哪些竞品车型上
- 逻辑更简单：只保留一条主路线，便于维护和排障

---

## 交互式搜索产品

项目现在提供了命令行交互搜索入口：

```powershell
py -3 search_cli.py --db db\bom.duckdb --qdrant db\qdrant_storage --api-key "your_bge_token"
```

### 当前唯一主路线：DuckDB First

流程：
1. DuckDB 先执行所有结构化过滤
2. 过滤后的候选 `id` 传给 Qdrant
3. Qdrant 只负责语义相似排序

说明：
- 这是当前产品唯一主路线
- Qdrant 只用于模糊/语义召回
- payload 仅用于结果展示和未来扩展预留，不承担当前性能优化职责

### 结构化查询示例

```powershell
py -3 search_cli.py --query "semantic=`"前门铰链`" vehicle_name=Tesla_Model3_2022.xlsx surface_treat=电泳 weight_kg<=0.5 top=5"
```

进入 REPL 后可用命令：
- `search ...`：结构化搜索
- `nl ...`：自然语言搜索
- `fields`：查看支持的字段
- `vehicles`：查看上一轮结果命中的车型汇总
- `show 1`：看某条结果完整字段
- `export result.csv`：导出上一轮结果
- `history`：查看本次会话查询历史

### 推荐输入方式

结合当前产品定位，推荐优先这样用：
- 先描述零部件和结构语义，例如：`前门铰链`、`仪表盘总成`、`前舱加强板`
- 再补材料、表面处理、重量、尺寸等条件
- 最后通过结果里的车型汇总去定位对应的点云或拆解图片

例如：

```text
search semantic="前门铰链" material~钢 surface_treat~电泳 weight_kg<=0.5
```

这里的语义是：
- `semantic="前门铰链"`：主语义召回
- `material~钢`、`surface_treat~电泳`：软匹配重排，优先把更像钢制/电泳件的结果排前面
- `weight_kg<=0.5`：硬过滤

如果你确实要严格限制材料或表面处理，仍然可以用 `=`：

```text
search semantic="前门铰链" material=钢 surface_treat=电泳
```

### 自然语言搜索（可接内网 LLM）

如果配置了内网 OpenAI-compatible LLM，可让系统把自然语言自动转成结构化检索命令：

```powershell
$env:SEARCH_LLM_API_BASE="https://your-llm-gateway/v1"
$env:SEARCH_LLM_API_KEY="your_llm_token"
$env:SEARCH_LLM_MODEL="your_model_name"

py -3 search_cli.py --api-key "your_bge_token"
```

如果你不想在 Windows 里设置环境变量，也可以直接传参：

```powershell
py -3 search_cli.py --api-key "your_bge_token" --llm-api-base "https://your-llm-gateway/v1" --llm-api-key "your_llm_token" --llm-model "your_model_name"
```

然后直接输入：

```text
nl 查找 Model3 上前门区域重量小于0.5kg、表面处理为电泳的铰链
```

系统会：
- 尝试抽取语义描述和结构化筛选条件
- 校验字段是否合法
- 如果用户提到库里没有的属性，给出提醒

---

## Streamlit 前端

项目现在提供一个本地运行的 Streamlit 前端，适合给工程师直接在浏览器里检索。

### 启动方式

PowerShell:

```powershell
py -3 -m streamlit run streamlit_app.py -- --db db\bom.duckdb --qdrant db\qdrant_storage --api-key "your_bge_token"
```

如果暂时不需要语义召回，也可以先不传 `--api-key`：

```powershell
py -3 -m streamlit run streamlit_app.py -- --db db\bom.duckdb --qdrant db\qdrant_storage
```

启动后，在浏览器打开：

```text
http://127.0.0.1:8501
```

### 页面能力

页面包含两种输入方式：
- 预置筛选输入框：材料、表面处理、工艺、层级关键词、借用车型、重量/总重量/长宽高深上限
- 自然语言输入框：直接输入工程师描述，让系统自动转成结构化查询
- 页面默认示例：`重量小于15kg的引擎盖`

页面结果默认展示：
- 车型
- 零部件名称
- 层级路径

如果用户填写了额外筛选条件，结果表格会自动补充对应属性列，例如：
- 输入了材料条件，就展示材料列
- 输入了重量条件，就展示重量列
- 输入了长度/宽度/高度条件，就展示对应尺寸列

页面下方还会自动汇总命中的车型，并支持直接导出当前结果 CSV，方便继续定位点云文件或拆解图片。
结果区会明确说明本次检索走的是哪条链路，例如：
- 直接目标件返回
- 全量过滤后语义排序
- 词面预筛后语义排序

返回条数说明：
- Streamlit 页面单次最多可请求 200 条结果
- 搜索核心允许更高的 `top_k`，命令行场景默认上限为 500

### 使用建议

- 只做结构化筛选时，不需要配置 embedding API key
- 要使用语义模糊召回时，需要传 `--api-key` 或设置 `BGE_API_KEY`
- 要使用自然语言转查询，建议再额外配置内网 LLM：

```powershell
$env:SEARCH_LLM_API_BASE="https://your-llm-gateway/v1"
$env:SEARCH_LLM_API_KEY="your_llm_token"
$env:SEARCH_LLM_MODEL="your_model_name"
```

然后再启动：

```powershell
py -3 -m streamlit run streamlit_app.py -- --db db\bom.duckdb --qdrant db\qdrant_storage --api-key "your_bge_token"
```

如果没有配置内网 LLM，前端仍然可以工作，只是自然语言输入会退回规则解析。

### 中文检索约定

当前产品默认按“用户只输入中文”来设计：
- 语义 query 会自动扩成中英混合术语，提升对英文零件名的召回
- 文本筛选值会做中英术语扩展，例如“钢”会同时匹配 `steel`
- 结构化条件始终由 DuckDB 处理，Qdrant 不负责属性筛选
- 当语义词本身就是明确零部件名时，系统会优先保留“零部件名称命中”或“末级层级命中”的结果，避免只因上层路径包含关键词而把子件一并召回

### 我额外补上的必要能力

除了搜索本身，我还补了几项工程上很有必要的能力：
- 查询 embedding 本地缓存：减少工程师反复改写 query 时的 API 调用
- 结果详情查看：便于人工判断召回是否合理
- 结果导出 CSV：便于后续对比和发给同事
- 字段清单和历史查询：降低学习成本

---

## 数据质量报告

pipeline 结束后自动输出，可随时查询：
```python
from core.db_duckdb import DuckDBStore
store = DuckDBStore("db/bom.duckdb")
print(store.quality_report())
```

| 字段 | 含义 |
|------|------|
| `name_coverage_pct` | 有名称的行占比 |
| `level_coverage_pct` | 有层级路径的行占比 |
| `name_missing_cnt` | 无法提取名称的行数（需人工检查） |
| `name_derived_cnt` | 从 Level 列推导名称的行数（形态A） |
