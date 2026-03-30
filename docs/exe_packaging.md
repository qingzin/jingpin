# EXE 打包与交付说明（Windows）

本文档说明如何在 **Windows** 环境下把项目打包成两个可执行文件并交付前端团队：

- `builder_tool.exe`：建库工具
- `search_service.exe`：检索服务（强制要求 API Key）

> 说明：在 Linux/macOS 上无法直接产出 Windows `.exe`，请在目标 Windows 环境执行以下步骤。

---

## 1. 环境准备

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

---

## 2. 一键打包

### 2.1 PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build_exe.ps1
```

### 2.2 CMD

```bat
packaging\build_exe.bat
```

---

## 3. 产物位置

打包完成后，输出在：

- `dist/builder_tool.exe`
- `dist/search_service.exe`

---

## 4. 标准交付包目录（建议）

```text
delivery/
├─ backend/
│  ├─ builder_tool.exe
│  ├─ search_service.exe
│  ├─ config.template.yaml
│  ├─ start_builder.bat
│  ├─ start_search_service.bat
│  └─ VERSION.txt
├─ db/
│  ├─ bom.duckdb
│  └─ qdrant_storage/
├─ data/
│  └─ pointcloud/
├─ frontend/
│  ├─ builder-runner/
│  └─ search-demo/
└─ docs/
   ├─ exe_packaging.md
   └─ frontend_integration.md
```

---

## 5. 运行方式

### 5.1 建库工具

先复制配置模板：

```powershell
copy config\config.template.yaml config.yaml
```

修改 `config.yaml` 后运行：

```powershell
.\dist\builder_tool.exe --config config.yaml --run-mode full
```

### 5.2 检索服务（API Key 必填）

```powershell
.\dist\search_service.exe --db db\bom.duckdb --qdrant db\qdrant_storage --api-key <YOUR_API_KEY> --model bge-m3 --host 0.0.0.0 --port 8080 --pointcloud-root data\pointcloud
```

---

## 6. 前端联调最小接口

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

## 7. 前端团队 10 分钟验收流程

1. 启动 `search_service.exe`（提供有效 `--api-key`）。
2. 调用 `/health`，确认 `status=ok` 且 `semantic_enabled=true`。
3. 调用 `/search` 获取结果并检查 `display.rows` 与 `results`。
4. 若有点云路径，点击 `pointcloud_download_url` 验证下载。
5. 调用 `/search/nl` 验证自然语言查询链路。

---

## 8. 故障排查矩阵

| 问题现象 | 可能原因 | 处理建议 |
|---|---|---|
| 服务启动失败，提示参数错误 | 未传 `--api-key` | 补充有效 API Key 后重启 |
| 端口占用 | 8080 被其他服务占用 | 改 `--port` 或释放端口 |
| `/download` 返回 403 | 请求路径不在 `--pointcloud-root` 下 | 修正点云根目录或下载路径 |
| `/download` 返回 404 | 文件不存在 | 检查建库写入路径与实际文件 |
| `/search` 返回 500 | DB/Qdrant 路径错误或数据未建好 | 检查 `--db`、`--qdrant`、先执行建库 |
| 语义结果质量低 | embedding 数据缺失或 key 异常 | 重跑建库并确认 embedding 正常 |

---

## 9. 版本与兼容约定

- 后端接口版本以交付包内 `VERSION.txt` 为准。
- 非破坏性升级允许新增字段，不删除既有字段。
- 若存在破坏性变更，必须提升版本号并同步更新前端文档。
