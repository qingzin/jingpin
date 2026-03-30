# search-demo

搜索服务前端示例，覆盖 `/health`、`/fields`、`/search`、`/search/nl` 与点云下载链接展示。

## 运行

```bash
cd frontend/search-demo
python -m http.server 5173
```

访问 `http://127.0.0.1:5173`。

## 说明

- 默认后端地址：`http://127.0.0.1:8080`
- 启动后先点 `Health`，会自动根据 `nl_enabled` 控制 NL 按钮可用性。
- `filters` 支持输入 JSON 数组。
