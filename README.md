# BOM + 点云后端工具（Builder + Search Service）

项目只交付后端能力，不包含前端页面代码。前端可按 API 文档自行实现页面与交互。

## 快速开始

```bash
python -m pip install -r requirements.txt
python builder_tool.py --config config.yaml --run-mode full
python search_service.py --db db/bom.duckdb --qdrant db/qdrant_storage --host 0.0.0.0 --port 8080
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

语义模式：

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

无 API Key 时自动降级为关键词检索（`/search` 可用，`/search/nl` 不可用）。

API：
- `GET /health`
- `GET /fields`
- `POST /search`（结构化检索）
- `POST /search/nl`（自然语言检索）
- `GET /download?path=...`（点云下载）

---

## 前端对接文档

前端需要实现哪些功能、每个接口的请求/响应字段、页面行为（检索输入、结果表格、车型汇总、点云下载按钮）统一见：

- `docs/frontend_integration.md`

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
