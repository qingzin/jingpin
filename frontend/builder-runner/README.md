# builder-runner

建库执行前端示例。通过 `frontend/local-bridge` 提供的本地 API 调用 `builder_tool.exe`。

## 运行

1. 启动 bridge：
   ```bash
   cd frontend/local-bridge
   python bridge_server.py
   ```
2. 用任意静态服务器打开当前目录（例如 `python -m http.server 5174`）。
3. 访问 `index.html`，配置 `builder_tool.exe` 路径并执行。

## 已知限制

- 仅演示本地联调，未做鉴权。
- 日志为轮询刷新。
