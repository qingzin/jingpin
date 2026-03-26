"""
search_engine.py
单一路线搜索核心：
1. 先提取目标件或目标描述做语义召回
2. 默认召回前 N 条候选（默认 500，可调小以提高速度）
3. 再对召回结果做属性筛选
"""
from __future__ import annotations

from dataclasses import dataclass, field
import difflib
import math
import time
from typing import Any, Optional

import pandas as pd

from core.query_expander import expand_filter_values, expand_text_query


FIELD_SPECS = {
    "vehicle_name": {"duckdb": "source_file", "type": "text", "ops": {"=", "~"}},
    "source_file": {"duckdb": "source_file", "type": "text", "ops": {"=", "~"}},
    "borrowed_vehicle_model": {"duckdb": "vehicle_model", "type": "text", "ops": {"=", "~"}},
    "part_name": {"duckdb": "part_name", "type": "text", "ops": {"=", "~"}},
    "part_number": {"duckdb": "part_number", "type": "text", "ops": {"=", "~"}},
    "manufacturer": {"duckdb": "manufacturer", "type": "text", "ops": {"=", "~"}},
    "material": {"duckdb": "material", "type": "text", "ops": {"=", "~"}},
    "material_type": {"duckdb": "material_type", "type": "text", "ops": {"=", "~"}},
    "material_grade": {"duckdb": "material_grade", "type": "text", "ops": {"=", "~"}},
    "surface_treat": {"duckdb": "surface_treat", "type": "text", "ops": {"=", "~"}},
    "process": {"duckdb": "process", "type": "text", "ops": {"=", "~"}},
    "system": {"duckdb": "system", "type": "text", "ops": {"=", "~"}},
    "part_type": {"duckdb": "part_type", "type": "text", "ops": {"=", "~"}},
    "location": {"duckdb": "location", "type": "text", "ops": {"=", "~"}},
    "detail": {"duckdb": "detail", "type": "text", "ops": {"=", "~"}},
    "form": {"duckdb": "form", "type": "text", "ops": {"="}},
    "weight_kg": {"duckdb": "weight_kg", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "total_weight_kg": {"duckdb": "total_weight_kg", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "quantity": {"duckdb": "quantity", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "length_mm": {"duckdb": "length_mm", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "width_mm": {"duckdb": "width_mm", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "height_mm": {"duckdb": "height_mm", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "depth_mm": {"duckdb": "depth_mm", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "thickness_mm": {"duckdb": "thickness_mm", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "diameter_mm": {"duckdb": "diameter_mm", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "level_depth": {"duckdb": "level_depth", "type": "number", "ops": {"=", ">", ">=", "<", "<="}},
    "level_contains": {"duckdb_special": "list_contains(level_array, ?)", "type": "text", "ops": {"=", "~"}},
}
FIELD_ALIASES = {
    "vehicle": "vehicle_name",
    "model": "vehicle_name",
    "source": "source_file",
    "level": "level_contains",
    "depth": "level_depth",
}
STRATEGIES = {"auto", "semantic_first", "duckdb_first"}
GENERIC_SEMANTIC_TERMS = {
    "零部件", "部件", "零件", "配件", "组件",
    "part", "parts", "component", "components",
}


@dataclass
class QueryFilter:
    field: str
    op: str
    value: Any


@dataclass
class SearchQuery:
    semantic_query: str = ""
    target_component: str = ""
    filters: list[QueryFilter] = field(default_factory=list)
    top_k: int = 100
    candidate_limit: int = 100
    strategy: str = "auto"


class SearchEngine:
    def __init__(self, duck_store, qdrant_store, embedder=None, query_cache=None):
        self.duck_store = duck_store
        self.qdrant_store = qdrant_store
        self.embedder = embedder
        self.query_cache = query_cache

    @staticmethod
    def supported_fields() -> list[dict]:
        return [
            {
                "field": name,
                "type": spec["type"],
                "ops": "".join(sorted(spec["ops"])),
                "soft_pref_with_~": "no",
                "duckdb_column": spec.get("duckdb") or spec.get("duckdb_special"),
            }
            for name, spec in FIELD_SPECS.items()
        ]

    def search(self, query: SearchQuery) -> dict:
        query, notes = self.validate_query(query)
        result = self._run_semantic_first(query)
        return {
            "mode": "single",
            "strategy": "semantic_first",
            "query": query,
            "notes": notes,
            "result": result,
        }

    def validate_query(self, query: SearchQuery) -> tuple[SearchQuery, list[str]]:
        notes = []
        normalized = []

        if query.strategy not in STRATEGIES:
            raise ValueError(f"不支持的策略: {query.strategy}。当前只支持 semantic_first。")

        for f in query.filters:
            field_name = self.normalize_field_name(f.field)
            if field_name not in FIELD_SPECS:
                suggestion = self.suggest_field(field_name)
                hint = f"；你是不是想写 `{suggestion}`？" if suggestion else ""
                raise ValueError(f"不支持的字段: `{f.field}`{hint}")
            spec = FIELD_SPECS[field_name]
            if f.op not in spec["ops"]:
                raise ValueError(f"字段 `{field_name}` 不支持操作符 `{f.op}`，可用: {sorted(spec['ops'])}")
            normalized.append(QueryFilter(field=field_name, op=f.op, value=self._coerce_value(field_name, f.value)))

        query.filters = normalized
        query.strategy = "semantic_first"
        original_semantic = expand_text_query((query.semantic_query or "").strip())
        query.semantic_query = self._strip_generic_semantic(original_semantic)
        if query.semantic_query != original_semantic:
            notes.append("已移除过于泛化的语义词，仅保留真正有区分度的零部件描述。")
        query.top_k = max(1, min(int(query.top_k), 1000))
        query.candidate_limit = query.top_k

        retrieval_text = self._semantic_text(query)
        if not retrieval_text:
            raise ValueError("当前只保留语义优先路径，请提供目标件或目标描述。")
        if query.filters:
            notes.append(f"当前按“先语义召回前 {query.top_k} 条，再做属性筛选”的单一路径执行搜索。")
        return query, notes

    def _run_semantic_first(self, query: SearchQuery) -> dict:
        t0 = time.time()
        retrieval_text = self._semantic_text(query)
        query_vector = self._embed_query(retrieval_text)
        hits = self.qdrant_store.search(query_vector=query_vector, top_k=query.top_k)
        hydrated = self._hydrate_hits(hits)
        filtered_results = self._apply_attribute_filters(hydrated, query.filters)

        if not filtered_results:
            notes = [
                f"已先对 `{retrieval_text}` 做语义召回，并在前 {query.top_k} 条候选里执行属性筛选。",
                "当前候选未满足属性筛选条件。可放宽筛选条件，或适当调大返回条数以扩大语义候选范围。",
            ]
            return self._empty_result(t0, notes=notes)

        return self._result(
            t0,
            len(hits),
            filtered_results,
            [f"已先对 `{retrieval_text}` 做语义召回，并在前 {query.top_k} 条候选里执行属性筛选。"],
            retrieval_mode="semantic_then_filter",
            retrieval_explanation="单一路径：先用目标件或目标描述做语义召回，再对召回结果执行属性筛选。",
        )

    def _semantic_text(self, query: SearchQuery) -> str:
        base_text = (query.target_component or query.semantic_query or "").strip()
        if not base_text:
            return ""
        return self._strip_generic_semantic(expand_text_query(base_text))

    def _apply_attribute_filters(self, results: list[dict], filters: list[QueryFilter]) -> list[dict]:
        if not results or not filters:
            return self._rerank_results(results)

        candidate_ids = [item["id"] for item in results]
        allowed_ids = set(self._filter_candidate_ids(filters, candidate_ids))
        filtered = [item for item in results if item["id"] in allowed_ids]
        return self._rerank_results(filtered)

    def _filter_candidate_ids(self, filters: list[QueryFilter], candidate_ids: list[int]) -> list[int]:
        sql = "SELECT id FROM parts"
        conditions, params = self._build_duckdb_conditions(filters, candidate_ids=candidate_ids)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        rows = self.duck_store.conn.execute(sql, params).fetchall()
        return [int(row[0]) for row in rows]

    @staticmethod
    def _rerank_results(results: list[dict]) -> list[dict]:
        for rank, item in enumerate(results, start=1):
            item["rank"] = rank
        return results

    def _embed_query(self, text: str) -> list[float]:
        if not self.embedder:
            raise ValueError("当前未配置 embedding API key，无法执行语义检索。")
        model = getattr(self.embedder, "model", "unknown")
        if self.query_cache is not None:
            cached = self.query_cache.get(text, model)
            if cached is not None:
                return cached
        vector = self.embedder.embed_single(text)
        if self.query_cache is not None:
            self.query_cache.set(text, model, vector)
        return vector

    def _hydrate_hits(self, hits: list[dict]) -> list[dict]:
        ids = [int(h["id"]) for h in hits]
        if not ids:
            return []
        rows_df = self.duck_store.get_rows_by_ids(ids)
        rows_map = {int(row["id"]): self._clean_row(row.to_dict()) for _, row in rows_df.iterrows()}
        results = []
        for rank, hit in enumerate(hits, start=1):
            row = rows_map.get(int(hit["id"]))
            if not row:
                continue
            results.append({
                "rank": rank,
                "id": int(hit["id"]),
                "score": round(float(hit["score"]), 4),
                "semantic_score": round(float(hit["score"]), 4),
                "payload": hit.get("payload", {}),
                "row": row,
            })
        return results


    def _build_duckdb_conditions(
        self,
        filters: list[QueryFilter],
        candidate_ids: Optional[list[int]] = None,
    ) -> tuple[list[str], list[Any]]:
        conditions = []
        params: list[Any] = []

        if candidate_ids is not None:
            if not candidate_ids:
                return ["1 = 0"], []
            placeholders = ", ".join(["?" for _ in candidate_ids])
            conditions.append(f"id IN ({placeholders})")
            params.extend(candidate_ids)

        for f in filters:
            spec = FIELD_SPECS[f.field]
            if "duckdb_special" in spec:
                conditions.append(spec["duckdb_special"])
                params.append(f.value)
                continue

            column = spec["duckdb"]
            if spec["type"] == "text":
                values = expand_filter_values(str(f.value))
                if f.op == "~":
                    clauses = [f"{column} ILIKE ?" for _ in values]
                    conditions.append("(" + " OR ".join(clauses) + ")")
                    params.extend([f"%{value}%" for value in values])
                else:
                    clauses = [f"{column} {f.op} ?" for _ in values]
                    conditions.append("(" + " OR ".join(clauses) + ")")
                    params.extend(values)
            else:
                conditions.append(f"{column} {f.op} ?")
                params.append(f.value)

        return conditions, params

    @staticmethod
    def _result(
        start_time: float,
        candidate_count: int,
        results: list[dict],
        notes: list[str],
        retrieval_mode: str,
        retrieval_explanation: str,
    ) -> dict:
        return {
            "strategy": "semantic_first",
            "elapsed_ms": round((time.time() - start_time) * 1000, 1),
            "candidate_count": candidate_count,
            "results": results,
            "notes": notes,
            "retrieval_mode": retrieval_mode,
            "retrieval_explanation": retrieval_explanation,
        }

    @staticmethod
    def _empty_result(start_time: float, notes: list[str]) -> dict:
        return {
            "strategy": "semantic_first",
            "elapsed_ms": round((time.time() - start_time) * 1000, 1),
            "candidate_count": 0,
            "results": [],
            "notes": notes,
            "retrieval_mode": "empty",
            "retrieval_explanation": "未返回结果：语义候选为空，或召回候选未满足属性筛选。",
        }

    @staticmethod
    def _clean_row(row: dict) -> dict:
        out = {}
        for k, v in row.items():
            if hasattr(v, "tolist"):
                converted = v.tolist()
                if isinstance(converted, list):
                    out[k] = converted
                    continue
                v = converted
            if isinstance(v, tuple):
                out[k] = list(v)
                continue
            if isinstance(v, float) and math.isnan(v):
                out[k] = None
            else:
                out[k] = v
        return out

    @staticmethod
    def normalize_field_name(name: str) -> str:
        return FIELD_ALIASES.get(name.strip(), name.strip())

    @staticmethod
    def suggest_field(name: str) -> Optional[str]:
        matches = difflib.get_close_matches(name, FIELD_SPECS.keys(), n=1, cutoff=0.5)
        return matches[0] if matches else None

    @staticmethod
    def _coerce_value(field_name: str, value: Any) -> Any:
        if FIELD_SPECS[field_name]["type"] == "number":
            try:
                return float(value)
            except ValueError as e:
                raise ValueError(f"字段 `{field_name}` 需要数值，但收到 `{value}`") from e
        return str(value).strip()

    @staticmethod
    def _strip_generic_semantic(text: str) -> str:
        if not text:
            return text
        chunks = [part.strip() for part in text.split("|")]
        kept = [chunk for chunk in chunks if chunk.lower().strip() not in GENERIC_SEMANTIC_TERMS]
        return " | ".join(kept).strip()

    @staticmethod
    def _normalize_match_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        return "".join(ch for ch in text if ch.isalnum())
