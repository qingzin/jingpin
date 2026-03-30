# BOM + 点云后端工具（Builder + Search Service）

项目交付后端能力，并附带搜索示例前端。

## 快速开始

```bash
python -m pip install -r requirements.txt
python builder_tool.py --config config.yaml --run-mode full
python search_service.py --db db/bom.duckdb --qdrant db/qdrant_storage --api-key YOUR_BEARER_TOKEN --host 0.0.0.0 --port 8080
```

---

## 工具 1：Builder（建库）

能力：
- 扫描 BOM 文件夹（`xlsx/xls/csv`）
- 表头仅在第 1/2 行二选一，支持第一行大量空值/unnamed 的场景
- 丢弃未命名列（可配置）
- 扫描点云目录（`.stl/.obj`）
- 同车型同名零部件关联 `pointcloud_path`
- 同车型无同名零部件写入 `record_type=pointcloud_only`
- 失败文件跳过并输出失败报告

命令：

```bash
python builder_tool.py --config config.yaml --run-mode full
```

配置模板见：`config/config.template.yaml`。

---

## 工具 2：Search Service（检索后端）

语义模式（API Key 必填）：

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

API：
- `GET /health`
- `GET /fields`
- `POST /search`（结构化检索）
- `POST /search/nl`（自然语言检索）
- `GET /download?path=...`（点云下载）

---

## 前端示例

- `frontend/search-demo`：搜索服务前端示例（预置可量化筛选字段输入（重量/长宽高深区间）；支持 `/health`、`/fields`、`/search`、`/search/nl`、`/download`）

前端对接细节见：`docs/frontend_integration.md`。

---

## 测试

```bash
pytest -q
```

---

## EXE 打包（Windows）

- `docs/exe_packaging.md`
- `packaging/build_exe.ps1`
- `packaging/build_exe.bat`
