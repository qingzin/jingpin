# EXE 打包与交付说明（Windows）

本文档说明如何在 **Windows** 环境下把项目打包成两个可执行文件并交付前端团队：

- `builder_tool.exe`：建库工具
- `search_gui.exe`：检索 GUI（强制要求 API Key）

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
- `dist/search_gui.exe`

---

## 4. 标准交付包目录（建议）

```text
delivery/
├─ backend/
│  ├─ builder_tool.exe
│  ├─ search_gui.exe
│  ├─ config.template.yaml
│  ├─ start_builder.bat
│  ├─ start_search_gui.bat
│  └─ VERSION.txt
├─ db/
│  ├─ bom.duckdb
│  └─ qdrant_storage/
├─ data/
│  └─ pointcloud/
├─ frontend/
│  └─ search-demo/
└─ docs/
   ├─ exe_packaging.md
   └─ frontend_integration.md
```

---

## 5. 运行方式

### 5.1 建库工具

双击 `builder_tool.exe`，在界面中输入模型名、API Key、DB 路径、BOM 目录、点云目录后点击“一键建库”。

### 5.2 检索 GUI（API Key 必填）

```powershell
.\dist\search_gui.exe
```

---

## 6. 检索 GUI 功能验收

- 输入 API Key 初始化检索能力
- 支持语义查询 + 属性筛选
- 结果动态展示数据库属性字段
- 支持点云文件下载

---

## 7. 前端团队 10 分钟验收流程

1. 启动 `search_gui.exe` 并输入有效 API Key。
2. 输入查询词执行检索，确认返回结果。
3. 增加数值/文本筛选，确认结果随条件变化。
4. 选中含点云路径的记录，点击下载并验证文件可保存。

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
