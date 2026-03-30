# 后端工具说明（Builder + Search Service）

## 1. Builder 建库工具

### 启动
```bash
python builder_tool.py --config config.yaml --run-mode full
```

### 关键能力
- 扫描 BOM 文件夹（xlsx/xls/csv）
- 表头第1/2行自适应识别
- 若第1行出现大量 unnamed/空值，会降低评分，优先选择第2行
- 未命名列（`_unnamed_*`）在最终入库前丢弃
- 失败文件自动跳过并写入失败报告
- 扫描点云目录（`.stl`/`.obj`）
- 同车型同名零部件：写入 `pointcloud_path`
- 同车型无同名零部件：以 `pointcloud_only` 写入主表

### 配置示例
```yaml
storage:
  duckdb_path: db/bom.duckdb
  qdrant_path: db/qdrant_storage
  vector_dim: 1024

input:
  bom_folder: D:/data/bom
  pointcloud_root: D:/data/pointcloud

builder:
  header_candidate_rows: [0, 1]
  min_header_score: 1
  drop_unnamed_columns: true
  fail_report_path: output/fail_report.csv

pointcloud:
  extensions: [".stl", ".obj"]

embedding:
  enabled: true
  api_key: "YOUR_BEARER_TOKEN"
  model: bge-m3
```

## 2. Search Service 检索工具

### 启动
```bash
python search_service.py --db db/bom.duckdb --qdrant db/qdrant_storage --api-key YOUR_TOKEN --model bge-m3 --host 0.0.0.0 --port 8080 --pointcloud-root D:/data/pointcloud
```

无 api-key 时自动降级为关键词检索：
```bash
python search_service.py --db db/bom.duckdb --qdrant db/qdrant_storage --host 0.0.0.0 --port 8080
```

### API

#### GET /health
返回服务状态以及语义/自然语言能力开关。

#### GET /fields
返回支持的筛选字段（给前端动态构建筛选器）。

#### POST /search
请求：
```json
{
  "query": "前门铰链",
  "top_k": 20,
  "filters": {
    "vehicle_name": "Tesla_Model3_2022"
  }
}
```

响应字段（每条结果）：
- `rank`
- `score`
- `part_name`
- `vehicle_name`
- `record_type` (`bom_part` / `pointcloud_only`)
- `part_number`
- `material`
- `level_path`
- `pointcloud_path`
- `pointcloud_download_url`

响应还包含：
- `display.columns` / `display.rows`（直接用于渲染结果表格）
- `display.vehicle_summary`（命中车型汇总）
- `notes`、`parsed_query`（用于前端提示与回显）

#### POST /search/nl
自然语言检索入口，返回结构与 `/search` 基本一致，并新增：
- `planner_notes`
- `unsupported_requirements`

#### GET /download?path=...
下载点云文件。服务会限制路径必须在 `--pointcloud-root` 下。

> 前端实现细节见：`docs/frontend_integration.md`
