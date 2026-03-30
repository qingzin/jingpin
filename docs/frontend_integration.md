# 前端对接说明（与历史前端功能保持一致）

本文档只描述前端开发需要实现的功能和接口对接方式，不包含前端代码实现。

## 1. 目标功能清单

前端页面保持与历史版本一致的核心体验：

1. 支持输入零部件语义查询（如“前门铰链”）。
2. 支持结构化筛选（车型、材料、工艺、重量等）。
3. 支持自然语言查询（如“查找 Model3 前门铰链，重量小于 0.5kg”）。
4. 展示检索摘要（耗时、候选数量、命中数量）。
5. 展示可视化结果表格（含层级路径、点云路径）。
6. 展示命中车型汇总（车型、命中数量、最佳分数）。
7. 若有点云文件，展示“下载点云”按钮并触发下载。

---

## 2. 服务启动约定

后端启动后默认地址示例：`http://127.0.0.1:8080`

如果启动时没有 `--api-key`：
- `POST /search` 仍可用（关键词降级模式）
- `POST /search/nl` 返回错误（前端应禁用“自然语言搜索”按钮）

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
- `semantic_enabled=false`：保留搜索功能，但提示“语义模式不可用，已降级关键词检索”。
- `nl_enabled=false` 或 `semantic_enabled=false`：禁用自然语言搜索入口。

---

### 3.2 `GET /fields`

用于构建“高级筛选”UI（字段名、字段类型、支持操作符）。

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

### 3.3 `POST /search`（结构化）

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

2) 明确操作符数组（推荐）：

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

成功响应字段：

- `strategy`：当前策略（`semantic_first`）
- `elapsed_ms`：耗时
- `candidate_count`：候选数
- `notes[]`：提示信息
- `parsed_query`：后端最终执行的查询串
- `query`：结构化查询对象
- `display.columns[]`：结果列定义（含展示标签）
- `display.rows[]`：结果表格行
- `display.vehicle_summary[]`：车型汇总
- `results[]`：简化结果（包含 `pointcloud_download_url`）

---

### 3.4 `POST /search/nl`（自然语言）

请求示例：

```json
{
  "query": "查找 Model3 前门铰链，重量小于0.5kg",
  "top_k": 20
}
```

响应在 `/search` 基础上新增：
- `planner_notes[]`：自然语言规划提示
- `unsupported_requirements[]`：无法表达的需求列表

---

### 3.5 `GET /download?path=...`

用于下载点云文件。

前端行为建议：
- 若 `pointcloud_download_url` 非空，渲染“下载点云”按钮。
- 点击后直接打开该 URL（新窗口或文件下载）。

---

## 4. 前端页面建议结构

## 4.1 查询区
- 结构化搜索输入框（必填）
- `top_k` 输入
- 高级筛选区（根据 `/fields` 渲染）
- “搜索”按钮（调用 `/search`）
- “自然语言搜索”按钮（调用 `/search/nl`，需 health 允许）

## 4.2 信息区
- 检索摘要：策略、耗时、候选数、命中数
- 提示信息：`notes` / `planner_notes`
- 查询串回显：`parsed_query`

## 4.3 结果区
- 主结果表格：使用 `display.columns` + `display.rows`
- 车型汇总表：使用 `display.vehicle_summary`
- 点云下载列：使用 `pointcloud_download_url`

---

## 5. 兼容性与错误处理

1. 前端需兼容两种返回模式：
   - `mode=semantic_or_fallback`
   - `mode=fallback_keyword`
2. HTTP 非 200 时，读取 `error` 字段提示用户。
3. 当 `/search/nl` 返回 400 且提示 embedding 未配置时，切换为普通 `/search` 模式。

---

## 6. 验收要点（前端）

1. 能完成结构化检索并正确展示表格。
2. 能展示车型汇总并随查询变化。
3. 当结果有点云路径时，下载按钮可直接下载文件。
4. 无 API Key 场景下，页面仍可检索（降级模式）。
5. 自然语言入口在不可用时能自动禁用。
