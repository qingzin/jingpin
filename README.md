# BOM + 点云 后端检索工具

本项目已精简为**纯后端**方案，交付形态为两个工具：

1. `builder_tool.py`：建库工具（BOM + 点云）
2. `search_service.py`：检索服务（HTTP API，供网页前端调用）

> 不包含前端页面实现。

---

## 1. 快速安装

```bash
python -m pip install -r requirements.txt
```

---

## 2. Builder（建库工具）

### 功能
- 读取 BOM 文件夹内全部 `xlsx/xls/csv`
- 表头自适应（只在第1/2行二选一）
- 可丢弃未命名列（`_unnamed_*`）
- 扫描点云目录（`.stl/.obj`）
- 同车型同名零部件：写入 `pointcloud_path`
- 同车型无同名零部件：写入 `record_type=pointcloud_only`
- 失败文件跳过并输出报告

### 启动
```bash
python builder_tool.py --config config.yaml --run-mode full
```

### 配置样例
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

---

## 3. Search Service（检索服务）

### 启动（语义模式）
```bash
python search_service.py \
  --db db/bom.duckdb \
  --qdrant db/qdrant_storage \
  --api-key YOUR_BEARER_TOKEN \
  --model bge-m3 \
  --host 0.0.0.0 \
  --port 8080 \
  --pointcloud-root D:/data/pointcloud
```

### 启动（降级关键词模式）
```bash
python search_service.py --db db/bom.duckdb --qdrant db/qdrant_storage --host 0.0.0.0 --port 8080
```

### API
- `GET /health`
- `POST /search`
- `GET /download?path=...`

`POST /search` 请求示例：
```json
{
  "query": "前门铰链",
  "top_k": 20,
  "filters": {
    "vehicle_name": "Tesla_Model3_2022"
  }
}
```

响应中包含：
- `part_name`
- `vehicle_name`
- `record_type`
- `pointcloud_path`
- `pointcloud_download_url`

---

## 4. 数据库关键字段

DuckDB 主表 `parts` 关键新增字段：
- `record_type`：`bom_part` / `pointcloud_only`
- `pointcloud_path`：点云文件路径（单值）

---

## 5. 测试

项目使用 pytest：

```bash
pytest -q
```

当前测试覆盖：
- 表头识别和未命名列处理
- 点云匹配与 pointcloud_only 入库
- 检索服务降级路径返回结构
