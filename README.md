# BOM + 点云工具（Windows GUI EXE 交付）

本项目提供两个可在 Windows 上双击运行的 GUI 程序：

- `builder_tool.exe`：建库 GUI（BOM+点云入库，支持增量更新与持续监控）
- `search_gui.exe`：检索 GUI（语义检索 + 属性筛选 + 点云下载）

---

## 一、你在 Windows 电脑上需要执行的操作

> 以下步骤只需要在 Windows 执行一次（首次打包/部署时）。

### 1) 安装 Python 与依赖

1. 安装 Python 3.10+（勾选 `Add Python to PATH`）
2. 打开 PowerShell，进入项目目录：

```powershell
cd <你的项目目录>\jingpin
```

3. 安装依赖：

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

---

### 2) 打包两个 EXE

执行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build_exe.ps1
```

打包后会在 `dist/` 目录得到（**one-folder 模式**）：

- `dist/builder_tool/builder_tool.exe`
- `dist/search_gui/search_gui.exe`

---

### 3) 运行建库 GUI（builder_tool.exe）

双击 `dist/builder_tool/builder_tool.exe` 后：

1. 输入 `Embedding 模型名`（默认 `bge-m3`）
2. 输入 `API Key`
3. 选择 `DuckDB 路径`
4. 选择 `Qdrant 存储目录`
5. 选择 `BOM 表路径文件夹`
6. 选择 `点云数据文件夹`
7. 点击 **一键建库**

功能说明：
- 若数据库已存在，默认按增量模式处理（跳过已存在来源文件）
- 勾选“持续监控”时，程序会每 5 秒扫描 BOM/点云文件夹
- 检测到新增或更新文件后，会自动执行增量更新

---

### 4) 运行检索 GUI（search_gui.exe）

双击 `dist/search_gui/search_gui.exe` 后：

1. 输入 `API Key`（必填）
2. 设置 `DuckDB` 与 `Qdrant` 路径
3. 点击 **初始化检索**
4. 输入查询词（例如“前门铰链”）
5. 选择筛选字段/操作符/值并添加筛选
6. 点击 **检索**

结果特点：
- 展示数据库中的动态属性列（不是固定死列）
- 支持模糊匹配（`~`）与数值比较（`>=` `<=` 等）
- 可选中一条结果并点击 **下载选中点云** 保存本地文件

---

## 二、常见问题

### 1) 初始化检索失败
- 先确认 API Key 有效
- 确认 DuckDB/Qdrant 路径正确
- 确认已先执行建库

### 1.1) `ModuleNotFoundError: No module named 'PySide6'`
- 这通常是 **Python 解释器不一致**：你安装 PySide6 的 conda 环境，和实际执行脚本/打包时使用的 Python 不是同一个。
- 请先确认解释器：
  - `python -c "import sys; print(sys.executable)"`
  - `python -m pip show PySide6`
- 再用同一个解释器执行打包脚本（脚本已包含 `pip install -r requirements.txt`）。
- 当前打包脚本已显式加入 `--collect-all PySide6 --collect-all shiboken6`，用于尽量避免 Qt 运行库缺失。

### 1.2) `ImportError: DLL load failed while importing QtCore`
- `builder_gui.py` 和 `search_gui.py` 同时报这个错，通常说明是 **本机 Python + PySide6 运行时环境** 问题，不是某个 GUI 脚本本身的问题。
- 处理步骤：
  1. 确认不要混用解释器（例如日志里同时出现 `Python313` 的 site-packages 和 `miniforge3` 路径）。建议显式指定解释器运行打包脚本：  
     - PowerShell：`packaging\build_exe.ps1 -Python D:\ProgramData\miniforge3\python.exe`  
     - CMD：`packaging\build_exe.bat D:\ProgramData\miniforge3\python.exe`
  2. 用同一个解释器重装 PySide6：`python -m pip uninstall -y PySide6 shiboken6 && python -m pip install --no-cache-dir PySide6`
  3. 在目标 Windows 机器安装 **Microsoft Visual C++ Redistributable 2015-2022 (x64)** 后重试。
  4. 删除旧产物 `build/`、`dist/` 后再执行打包脚本。

### 1.3) `NumPy was built with baseline optimizations (X86_V2)`
- 这是目标机器 CPU 指令集较老，和当前打包环境里安装的 NumPy 二进制不兼容导致。
- 项目已固定 `numpy==1.26.4` 与 `pandas==2.1.4`（避免新版本二进制兼容性问题），请先重新安装依赖再打包：
  - `python -m pip install -r requirements.txt --force-reinstall`
- 然后删除旧产物 `build/`、`dist/` 后重新执行打包脚本。

### 2) 检索不到结果
- 尝试放宽筛选条件
- 调大 `top_k`
- 检查建库时 BOM 与点云目录是否正确

### 3) 点云下载失败
- 结果中没有 `pointcloud_path`
- 或原始点云文件已被移动/删除

---

## 三、开发者说明

- 建库 GUI 入口：`builder_gui.py`
- 检索 GUI 入口：`search_gui.py`
- 兼容 CLI 建库脚本：`builder_tool.py`
- 打包脚本：
  - `packaging/build_exe.ps1`（PowerShell）
  - `packaging/build_exe.bat`（CMD）
