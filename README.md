# BOM + 点云后端工具交付说明（EXE）

本文档面向拿到交付包的前端/测试同学，只说明如何在 Windows 上直接使用 EXE 完成建库与检索。

## 1. 交付物

最少应包含：

- `dist/builder_tool.exe`
- `dist/search_service.exe`
- `config/config.template.yaml`
- `db/`（建库后会生成或更新 `bom.duckdb`、`qdrant_storage`）
- `data/pointcloud/`（如需下载点云）

---

## 2. 建库执行

1. 复制配置模板：

```powershell
copy config\config.template.yaml config.yaml
```

2. 修改 `config.yaml` 中 BOM 目录、点云目录、存储目录等参数。

3. 执行建库：

```powershell
.\dist\builder_tool.exe --config config.yaml --run-mode full
```

---

## 3. 启动检索服务

> `--api-key` 必填。

```powershell
.\dist\search_service.exe --db db\bom.duckdb --qdrant db\qdrant_storage --api-key <YOUR_API_KEY> --model bge-m3 --host 0.0.0.0 --port 8080 --pointcloud-root data\pointcloud
```

服务默认示例地址：`http://127.0.0.1:8080`

---

## 4. 联调接口

- `GET /health`
- `GET /fields`
- `POST /search`
- `POST /search/nl`
- `GET /download?path=...`

示例：

```powershell
curl http://127.0.0.1:8080/health
```

```powershell
curl -X POST http://127.0.0.1:8080/search -H "Content-Type: application/json" -d '{"query":"前门铰链","top_k":20}'
```

---

## 5. 搜索示例前端

交付包内示例前端目录：`frontend/search-demo`。

运行后可验证：
- 健康检查
- 结构化搜索 / 自然语言搜索
- 重量/长宽高深筛选
- 点云下载按钮

详细字段与前端约定见：`docs/frontend_integration.md`。

---

## 6. 更多说明

- EXE 打包说明：`docs/exe_packaging.md`
- 后端工具说明：`docs/backend_tools.md`
