# local-bridge

本地联调桥接服务（示例），用于让前端通过 HTTP 触发 `builder_tool.exe`。

## 启动

```bash
python bridge_server.py
```

默认监听：`http://127.0.0.1:18081`

## API

- `POST /api/builder/run`
- `GET /api/builder/status`

> 注意：仅用于本地开发示例，不建议直接用于生产环境。
