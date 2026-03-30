# EXE 打包与交付说明

本文档说明如何在 **Windows** 环境下把项目打包成两个可执行文件：

- `builder_tool.exe`：建库工具
- `search_service.exe`：检索服务

> 说明：在 Linux/macOS 上无法直接产出 Windows `.exe`，请在目标 Windows 环境执行以下步骤。

---

## 1. 环境准备

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

---

## 2. 一键打包

### PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build_exe.ps1
```

### CMD

```bat
packaging\build_exe.bat
```

---

## 3. 产物位置

打包完成后，输出在：

- `dist/builder_tool.exe`
- `dist/search_service.exe`

---

## 4. 运行方式

### 4.1 建库工具

先复制配置模板：

```powershell
copy config\config.template.yaml config.yaml
```

修改 `config.yaml` 后运行：

```powershell
.\dist\builder_tool.exe --config config.yaml --run-mode full
```

### 4.2 检索服务

```powershell
.\dist\search_service.exe --db db\bom.duckdb --qdrant db\qdrant_storage --api-key <YOUR_API_KEY> --model bge-m3 --host 0.0.0.0 --port 8080 --pointcloud-root data\pointcloud
```

---

## 5. 前端联调最小接口

- `GET /health`
- `POST /search`
- `GET /download?path=...`

示例：

```powershell
curl http://127.0.0.1:8080/health
```

```powershell
curl -X POST http://127.0.0.1:8080/search -H "Content-Type: application/json" -d '{"query":"前门铰链","top_k":20}'
```

---

## 6. 常见问题

### Q1: 打包后运行报缺少 DLL/依赖
- 确认在目标 Windows 机器重新执行过 `pip install -r requirements.txt`
- 重新执行打包脚本，确保使用同一 Python 版本

### Q2: 构建成功但搜索无语义结果
- 检查 `--api-key` 是否有效
- 检查建库阶段是否已启用 embedding 并成功写入向量

### Q3: download 返回 403
- 检查请求的文件路径是否在 `--pointcloud-root` 指定目录下
