# 前端对接说明（交付版）

本文档描述前端开发需要实现的功能、接口与错误处理策略。

## 1. 目标功能清单

1. 支持输入零部件语义查询（如“前门铰链”）。
2. 支持结构化筛选（车型、材料、工艺、重量等）。
3. 支持自然语言查询（如“查找 Model3 前门铰链，重量小于 0.5kg”）。
4. 展示检索摘要（耗时、候选数量、命中数量）。
5. 展示结果表格（含层级路径、点云路径）。
6. 展示命中车型汇总。
7. 点云下载按钮联动 `/download`。

---

## 2. 服务启动约定

后端默认地址示例：`http://127.0.0.1:8080`。

**强制要求：必须提供 `--api-key`。**

- 未提供 API Key 的服务实例视为不可交付。
- 前端无需适配“无 key 关键词降级”模式。

---

## 3. API 总览

### 3.1 `GET /health`

用于页面初始化探测能力开关。

响应示例：

```json
{
  "status": "ok",
  "semantic_enabled": true,
  "nl_enabled": true,
  "llm_enabled": false
}
```

前端行为建议：
- `semantic_enabled=false`：提示服务异常并禁用检索按钮。
- `nl_enabled=false`：禁用自然语言入口。

---

### 3.2 `GET /fields`

用于构建“高级筛选”UI。

响应示例：

```json
{
  "fields": [
    { "field": "vehicle_name", "type": "text", "ops": "=~" },
    { "field": "weight_kg", "type": "number", "ops": "<<=>>=" }
  ]
}
```

---

### 3.3 `POST /search`

请求体支持两种 `filters` 格式：

1) 简单字典（默认 `=`）：

```json
{
  "query": "前门铰链",
  "top_k": 20,
  "filters": {
    "vehicle_name": "Tesla_Model3_2022"
  }
}
```

2) 明确操作符数组：

```json
{
  "query": "前门铰链",
  "top_k": 20,
  "filters": [
    { "field": "vehicle_name", "op": "~", "value": "Model3" },
    { "field": "weight_kg", "op": "<=", "value": 0.5 }
  ]
}
```

成功响应关键字段：

- `mode`：固定为 `semantic`
- `strategy`：`semantic_first`
- `elapsed_ms`
- `candidate_count`
- `notes[]`
- `parsed_query`
- `query`
- `display.columns[]` / `display.rows[]` / `display.vehicle_summary[]`
- `results[]`（含 `pointcloud_download_url`）

---

### 3.4 `POST /search/nl`

请求示例：

```json
{
  "query": "查找 Model3 前门铰链，重量小于0.5kg",
  "top_k": 20
}
```

响应在 `/search` 基础上新增：

- `planner_notes[]`
- `unsupported_requirements[]`

---

### 3.5 `GET /download?path=...`

用于下载点云文件。

前端建议：
- `pointcloud_download_url` 非空时显示“下载点云”按钮。
- 点击后直接打开 URL 触发下载。

---

## 4. 页面建议结构

### 4.1 查询区
- 搜索输入框（必填）
- `top_k`
- 高级筛选（由 `/fields` 生成）
- “搜索”按钮（`/search`）
- “自然语言搜索”按钮（`/search/nl`）

### 4.2 信息区
- 策略、耗时、候选数、命中数
- `notes` / `planner_notes`
- `parsed_query` 回显

### 4.3 结果区
- 主结果表格（`display.columns` + `display.rows`）
- 车型汇总（`display.vehicle_summary`）
- 点云下载列

---

## 5. 兼容性与错误处理

1. HTTP 非 200 时，统一读取 `error` 字段提示用户。
2. `/search` 返回 503 时，提示“后端配置异常（embedding 未初始化）”。
3. `/search/nl` 返回 400 且 `nl planner 未启用` 时，提示“自然语言能力不可用”。

---

## 6. 示例前端目录与运行说明

- `frontend/builder-runner`：建库执行页面 + README。
- `frontend/search-demo`：搜索示例页面 + README。
- `frontend/local-bridge`：本地 bridge（负责执行 exe 与暴露本地 API）。

按各目录 README 即可本地启动。

---

## 7. 验收要点（前端）

1. 能完成结构化检索并正确展示表格。
2. 能展示车型汇总并随查询变化。
3. 当结果有点云路径时，下载按钮可触发下载。
4. 自然语言入口可用时可正确返回结果，不可用时自动禁用。
5. 文案与错误提示可被测试人员复现验证。
