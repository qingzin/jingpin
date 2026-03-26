"""
query_parser.py
解析工程师显式搜索语法，并提供可选的自然语言转结构化查询能力。
"""
from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass
from typing import Optional

import requests

from core.query_expander import TERM_GROUPS
from core.search_engine import FIELD_SPECS, SearchQuery, QueryFilter

TOKEN_PATTERN = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(>=|<=|=|>|<|~)(.+)$")
TARGET_SUFFIXES = (
    "仪表盘左侧出风口总成", "仪表盘右侧出风口总成",
    "仪表板左侧出风口总成", "仪表板右侧出风口总成",
    "出风口总成",
    "引擎盖", "发动机盖", "仪表盘", "仪表板", "出风口", "铰链", "支架", "加强板",
    "卡扣", "密封条", "门板", "门槛", "横梁", "护板", "固定件", "盖板", "饰板",
    "骨架", "总成", "hood", "bonnet", "hinge", "bracket", "clip", "seal", "panel",
)
TARGET_STOPWORDS = {
    "查找", "搜索", "帮我找", "一下", "一下子", "并且", "而且", "要求", "需要", "重量",
    "总重量", "长度", "宽度", "高度", "深度", "厚度", "直径", "小于", "大于", "等于",
    "不超过", "不少于", "低于", "高于", "前", "后", "左", "右", "上", "下",
    "钢", "铝", "塑料", "橡胶", "泡沫", "电泳", "喷涂", "镀锌",
}


def parse_structured_query(text: str, default_strategy: str = "auto") -> SearchQuery:
    tokens = shlex.split(text)
    if tokens and tokens[0] == "search":
        tokens = tokens[1:]

    semantic_parts = []
    filters = []
    top_k = 100
    candidate_limit = 100
    strategy = default_strategy

    for token in tokens:
        if token.startswith("semantic="):
            semantic_parts = [token.split("=", 1)[1]]
            continue
        if token.startswith("top="):
            top_k = int(token.split("=", 1)[1])
            continue
        if token.startswith("candidate_limit="):
            candidate_limit = int(token.split("=", 1)[1])
            continue
        if token.startswith("strategy="):
            strategy = token.split("=", 1)[1]
            continue

        m = TOKEN_PATTERN.match(token)
        if m:
            field, op, value = m.groups()
            filters.append(QueryFilter(field=field, op=op, value=value))
        else:
            semantic_parts.append(token)

    return SearchQuery(
        semantic_query=" ".join(semantic_parts).strip(),
        target_component=infer_target_component(" ".join(semantic_parts).strip()),
        filters=filters,
        top_k=top_k,
        candidate_limit=candidate_limit,
        strategy=strategy,
    )


@dataclass
class PlannerOutput:
    query: SearchQuery
    notes: list[str]
    unsupported_requirements: list[str]


class NaturalLanguagePlanner:
    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 30,
    ):
        self.api_base = api_base or os.environ.get("SEARCH_LLM_API_BASE")
        self.api_key = api_key or os.environ.get("SEARCH_LLM_API_KEY")
        self.model = model or os.environ.get("SEARCH_LLM_MODEL")
        self.timeout = timeout

    def plan(self, text: str) -> PlannerOutput:
        if self.api_base and self.api_key and self.model:
            try:
                return self._plan_with_llm(text)
            except Exception as e:
                fallback = self._plan_with_rules(text)
                fallback.notes.insert(0, f"LLM 规划失败，已退回规则解析: {e}")
                return fallback

        fallback = self._plan_with_rules(text)
        fallback.notes.insert(0, "未配置内网 LLM，已使用规则解析。")
        return fallback

    def _plan_with_llm(self, text: str) -> PlannerOutput:
        schema_lines = []
        for field_name, spec in FIELD_SPECS.items():
            schema_lines.append(
                f"- {field_name}: type={spec['type']}, ops={sorted(spec['ops'])}"
            )

        prompt = f"""
你是 BOM 检索命令规划器。请把用户的自然语言需求转成 JSON。

可用字段：
{chr(10).join(schema_lines)}

要求：
1. 只输出 JSON，不要输出解释文字
2. JSON 格式:
{{
  "semantic_query": "用于向量召回的结构性描述",
  "filters": [{{"field": "vehicle_name", "op": "=", "value": "Tesla_Model3_2022.xlsx"}}],
  "top_k": 100,
  "strategy": "auto",
  "unsupported_requirements": ["用户提到了数据库里不存在的字段"]
}}
3. 如果用户提到了数据库里没有的字段或无法表达的要求，请写入 unsupported_requirements
4. 语义 query 只保留适合语义检索的结构/部件描述，不要把重量尺寸材料供应商塞进去
5. `vehicle_name` 只在用户明确要求“限定某车型/某来源文件”时才使用；默认应优先搜索零部件，再返回命中车型
"""

        url = self.api_base.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "你是严谨的结构化查询规划器。"},
                {"role": "user", "content": prompt + "\n\n用户需求：" + text},
            ],
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _extract_json(content)

        filters = [
            QueryFilter(field=item["field"], op=item["op"], value=item["value"])
            for item in data.get("filters", [])
        ]
        query = SearchQuery(
            semantic_query=data.get("semantic_query", ""),
            filters=filters,
            top_k=int(data.get("top_k", 100)),
            strategy=data.get("strategy", "auto"),
        )
        query, rewrite_notes, unsupported = self._post_process_query(query, original_text=text)
        return PlannerOutput(
            query=query,
            notes=["使用内网 LLM 完成自然语言规划。"] + rewrite_notes,
            unsupported_requirements=data.get("unsupported_requirements", []) + unsupported,
        )

    def _plan_with_rules(self, text: str) -> PlannerOutput:
        filters = []
        notes = []
        unsupported = []
        working = text

        numeric_rules = [
            (r"(?:重量|重)\s*(?:=|等于|为)\s*([0-9.]+)\s*kg?", "weight_kg", "="),
            (r"(?:重量|重)\s*(?:<=|小于等于|不超过)\s*([0-9.]+)\s*kg?", "weight_kg", "<="),
            (r"(?:重量|重)\s*(?:>=|大于等于|不少于)\s*([0-9.]+)\s*kg?", "weight_kg", ">="),
            (r"(?:重量|重)\s*(?:<|小于|低于)\s*([0-9.]+)\s*kg?", "weight_kg", "<"),
            (r"(?:重量|重)\s*(?:>|大于|超过|高于)\s*([0-9.]+)\s*kg?", "weight_kg", ">"),
            (r"(?:厚度|料厚)\s*(?:=|等于|为)\s*([0-9.]+)\s*mm?", "thickness_mm", "="),
            (r"(?:厚度|料厚)\s*(?:<=|小于等于|不超过)\s*([0-9.]+)\s*mm?", "thickness_mm", "<="),
            (r"(?:厚度|料厚)\s*(?:>=|大于等于|不少于)\s*([0-9.]+)\s*mm?", "thickness_mm", ">="),
            (r"(?:厚度|料厚)\s*(?:<|小于|低于)\s*([0-9.]+)\s*mm?", "thickness_mm", "<"),
            (r"(?:厚度|料厚)\s*(?:>|大于|超过|高于)\s*([0-9.]+)\s*mm?", "thickness_mm", ">"),
            (r"(?:长度|长)\s*(?:=|等于|为)\s*([0-9.]+)\s*mm?", "length_mm", "="),
            (r"(?:长度|长)\s*(?:<=|小于等于|不超过)\s*([0-9.]+)\s*mm?", "length_mm", "<="),
            (r"(?:长度|长)\s*(?:>=|大于等于|不少于)\s*([0-9.]+)\s*mm?", "length_mm", ">="),
            (r"(?:长度|长)\s*(?:<|小于|低于)\s*([0-9.]+)\s*mm?", "length_mm", "<"),
            (r"(?:长度|长)\s*(?:>|大于|超过|高于)\s*([0-9.]+)\s*mm?", "length_mm", ">"),
            (r"(?:宽度|宽)\s*(?:=|等于|为)\s*([0-9.]+)\s*mm?", "width_mm", "="),
            (r"(?:宽度|宽)\s*(?:<=|小于等于|不超过)\s*([0-9.]+)\s*mm?", "width_mm", "<="),
            (r"(?:宽度|宽)\s*(?:>=|大于等于|不少于)\s*([0-9.]+)\s*mm?", "width_mm", ">="),
            (r"(?:宽度|宽)\s*(?:<|小于|低于)\s*([0-9.]+)\s*mm?", "width_mm", "<"),
            (r"(?:宽度|宽)\s*(?:>|大于|超过|高于)\s*([0-9.]+)\s*mm?", "width_mm", ">"),
            (r"(?:高度|高)\s*(?:=|等于|为)\s*([0-9.]+)\s*mm?", "height_mm", "="),
            (r"(?:高度|高)\s*(?:<=|小于等于|不超过)\s*([0-9.]+)\s*mm?", "height_mm", "<="),
            (r"(?:高度|高)\s*(?:>=|大于等于|不少于)\s*([0-9.]+)\s*mm?", "height_mm", ">="),
            (r"(?:高度|高)\s*(?:<|小于|低于)\s*([0-9.]+)\s*mm?", "height_mm", "<"),
            (r"(?:高度|高)\s*(?:>|大于|超过|高于)\s*([0-9.]+)\s*mm?", "height_mm", ">"),
            (r"层级深度\s*(?:<=|小于等于|不超过)\s*([0-9.]+)", "level_depth", "<="),
        ]
        text_rules = [
            (r"材料(?:为|是|包含)?([^\s，,。；;]+)", "material", "~"),
            (r"表面处理(?:为|是|包含)?([^\s，,。；;]+)", "surface_treat", "~"),
            (r"(?:供应商|制造商)(?:为|是|包含)?([^\s，,。；;]+)", "manufacturer", "~"),
            (r"层级(?:包含|在)?([^\s，,。；;]+)", "level_contains", "~"),
        ]

        for pattern, field, op in numeric_rules:
            m = re.search(pattern, working)
            if m:
                filters.append(QueryFilter(field=field, op=op, value=m.group(1)))
                working = working.replace(m.group(0), " ")

        for pattern, field, op in text_rules:
            m = re.search(pattern, working)
            if m:
                filters.append(QueryFilter(field=field, op=op, value=m.group(1)))
                working = working.replace(m.group(0), " ")

        if "颜色" in text:
            unsupported.append("颜色")
        if "硬度" in text:
            unsupported.append("硬度")

        semantic_query = re.sub(r"\s+", " ", working)
        semantic_query = re.sub(r"(查找|搜索|帮我找|一下|一下子|并且|而且|要求|需要|的|上|里|中)", " ", semantic_query)
        semantic_query = re.sub(r"\s+", " ", semantic_query).strip(" ，,。；;")
        if not semantic_query:
            notes.append("规则解析没有提取出独立语义描述，后续只会执行结构化过滤。")

        query, rewrite_notes, extra_unsupported = self._post_process_query(SearchQuery(
            semantic_query=semantic_query,
            filters=filters,
            strategy="auto",
        ), original_text=text)
        return PlannerOutput(
            query=query,
            notes=notes + rewrite_notes,
            unsupported_requirements=unsupported + extra_unsupported,
        )

    def _post_process_query(self, query: SearchQuery, original_text: str = "") -> tuple[SearchQuery, list[str], list[str]]:
        notes = []
        unsupported = []
        merged_semantic_parts = [query.semantic_query] if query.semantic_query else []
        rewritten_filters = []

        for f in query.filters:
            value_str = str(f.value).strip()

            # LLM 往往把结构名词误下推成过窄过滤，优先保留到 semantic 中。
            if f.field in {"part_name", "location", "detail"}:
                merged_semantic_parts.append(value_str)
                notes.append(f"已将 `{f.field}{f.op}{value_str}` 并入语义描述，避免过窄过滤。")
                continue

            # 自然语言里说 “Model3” 一般不是完整 source_file，改成模糊匹配。
            if f.field == "vehicle_name" and f.op == "=" and not _looks_like_filename(value_str):
                rewritten_filters.append(QueryFilter(field="vehicle_name", op="~", value=value_str))
                notes.append(f"已将 `vehicle_name={value_str}` 放宽为模糊匹配。")
                continue

            # 精确尺寸等值匹配在拆解 BOM 中命中率很低，自动扩成窄范围更实用。
            if f.field in {"length_mm", "width_mm", "height_mm", "depth_mm", "thickness_mm", "diameter_mm"} and f.op == "=":
                value = float(f.value)
                rewritten_filters.append(QueryFilter(field=f.field, op=">=", value=max(0, value - 1)))
                rewritten_filters.append(QueryFilter(field=f.field, op="<=", value=value + 1))
                notes.append(f"已将 `{f.field}={value}` 改写为 ±1mm 范围匹配。")
                continue

            rewritten_filters.append(f)

        query.semantic_query = _join_unique_semantic_parts(merged_semantic_parts)
        query.filters = _dedupe_filters(rewritten_filters)
        target_component = infer_target_component(original_text or query.semantic_query)
        if target_component:
            query.target_component = target_component
            normalized_semantic = _normalize_text_for_dedupe(query.semantic_query)
            normalized_target = _normalize_text_for_dedupe(target_component)
            if normalized_target and normalized_target not in normalized_semantic:
                query.semantic_query = f"{target_component} {query.semantic_query}".strip()
                notes.append(f"已抽取目标件 `{target_component}` 并并入语义描述。")
            else:
                notes.append(f"已识别目标件 `{target_component}`。")
        return query, notes, unsupported


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text)
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def _looks_like_filename(text: str) -> bool:
    lowered = text.lower()
    return lowered.endswith((".xlsx", ".xls", ".csv")) or "\\" in text or "/" in text


def _dedupe_filters(filters: list[QueryFilter]) -> list[QueryFilter]:
    seen = set()
    deduped = []
    for f in filters:
        key = (f.field, f.op, str(f.value))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped


def infer_target_component(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    candidates: list[tuple[int, str]] = []
    lowered = text.lower()

    for match in _extract_suffix_candidates(text):
        cleaned = _clean_target_candidate(match)
        if cleaned and cleaned not in TARGET_STOPWORDS:
            candidates.append((40, cleaned))

    for group in TERM_GROUPS:
        for term in group:
            term_lower = term.lower()
            if term_lower in lowered and term not in TARGET_STOPWORDS and any(sfx in term_lower for sfx in TARGET_SUFFIXES):
                candidates.append((10, term))

    if not candidates:
        return ""

    cleaned_candidates = []
    for base_score, candidate in candidates:
        cleaned = _clean_target_candidate(candidate)
        if cleaned and cleaned not in TARGET_STOPWORDS:
            cleaned_candidates.append((base_score, cleaned))

    cleaned_candidates.sort(
        key=lambda item: (_target_priority(item[1]) + item[0], len(item[1])),
        reverse=True,
    )
    return cleaned_candidates[0][1] if cleaned_candidates else ""


def _extract_suffix_candidates(text: str) -> list[str]:
    candidates = []
    for suffix in sorted(TARGET_SUFFIXES, key=len, reverse=True):
        for match in re.finditer(re.escape(suffix), text, flags=re.IGNORECASE):
            start, end = match.span()
            left = start
            right = end
            while left > 0 and _is_target_char(text[left - 1]):
                left -= 1
            while right < len(text) and _is_target_char(text[right]):
                right += 1
            candidates.append(text[left:right])
    return list(dict.fromkeys(candidates))


def _is_target_char(ch: str) -> bool:
    return ch.isalnum() or ("\u4e00" <= ch <= "\u9fff")


def _target_priority(text: str) -> int:
    lowered = text.lower()
    score = 0
    for idx, suffix in enumerate(TARGET_SUFFIXES):
        if suffix.lower() in lowered:
            score = max(score, len(TARGET_SUFFIXES) - idx)
    if re.search(r"[0-9]", text):
        score -= 20
    if any(stop in text for stop in TARGET_STOPWORDS):
        score -= 10
    return score


def _clean_target_candidate(text: str) -> str:
    text = text.strip(" ，,。；;")
    text = re.sub(r"^(查找|搜索|帮我找|请找|请搜索)", "", text)
    text = re.sub(r"^[A-Za-z0-9\u4e00-\u9fff]*(?:小于|大于|等于|不超过|不少于|低于|高于)[^的]*的", "", text)
    text = re.sub(r"^(重量|总重量|长度|宽度|高度|深度|厚度|直径|宽高深|长宽高|长宽高深)[^的]*的", "", text)
    return text.strip(" ，,。；;")


def _normalize_text_for_dedupe(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip()).lower()


def _join_unique_semantic_parts(parts: list[str]) -> str:
    seen = set()
    kept = []
    for part in parts:
        cleaned = (part or "").strip()
        if not cleaned:
            continue
        normalized = _normalize_text_for_dedupe(cleaned)
        if normalized in seen:
            continue
        seen.add(normalized)
        kept.append(cleaned)
    return " ".join(kept).strip()
