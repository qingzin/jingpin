"""streamlit_app.py
兼容层：保留历史模块名，但移除前端依赖。

当前文件只提供后端检索能力：
- 运行时构建（DuckDB/Qdrant/embedder）
- 执行结构化语义查询
- 返回 JSON 可序列化结果
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import BGEEmbedder
from core.query_cache import QueryEmbeddingCache
from core.query_parser import infer_target_component
from core.search_engine import QueryFilter, SearchEngine, SearchQuery
from core.search_presenter import present_results


def parse_args():
    parser = argparse.ArgumentParser(description="Backend search runner")
    parser.add_argument("--db", default="db/bom.duckdb")
    parser.add_argument("--qdrant", default="db/qdrant_storage")
    parser.add_argument("--cache-db", default="db/query_cache.duckdb")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--vector-dim", type=int, default=1024)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--query", default="")
    parser.add_argument("--top-k", type=int, default=20)
    return parser.parse_args()


def build_runtime(
    db_path: str,
    qdrant_path: str,
    cache_db: str,
    api_key: str | None,
    vector_dim: int,
    batch: int,
):
    duck_store = DuckDBStore(db_path)
    duck_store.init_schema()

    qdrant_store = QdrantStore(qdrant_path)
    qdrant_store.init_collection(dim=vector_dim)

    embedder = None
    actual_api_key = api_key or os.environ.get("BGE_API_KEY")
    if actual_api_key:
        embedder = BGEEmbedder(api_key=actual_api_key, batch_size=batch)

    query_cache = QueryEmbeddingCache(cache_db)
    engine = SearchEngine(
        duck_store=duck_store,
        qdrant_store=qdrant_store,
        embedder=embedder,
        query_cache=query_cache,
    )
    return {
        "engine": engine,
        "embedder_enabled": embedder is not None,
    }


def run_query(runtime: dict, text: str, top_k: int = 20, filters: dict | None = None) -> dict:
    filters = filters or {}
    query_filters = [
        QueryFilter(field=key, op="=", value=value)
        for key, value in filters.items()
        if value not in (None, "")
    ]

    query = SearchQuery(
        semantic_query=text.strip(),
        target_component=infer_target_component(text),
        filters=query_filters,
        top_k=top_k,
        strategy="semantic_first",
    )

    if not runtime["embedder_enabled"]:
        raise ValueError("当前未配置 embedding API key，无法执行语义检索。")

    response = runtime["engine"].search(query)
    result = response["result"]
    display = present_results(result["results"], response["query"].filters)
    return {
        "strategy": response["strategy"],
        "elapsed_ms": result["elapsed_ms"],
        "candidate_count": result["candidate_count"],
        "notes": [*response["notes"], *result["notes"]],
        "query": {
            "semantic_query": response["query"].semantic_query,
            "target_component": response["query"].target_component,
            "top_k": response["query"].top_k,
            "filters": [asdict(f) for f in response["query"].filters],
        },
        "display": display,
    }


def main():
    args = parse_args()
    runtime = build_runtime(
        db_path=args.db,
        qdrant_path=args.qdrant,
        cache_db=args.cache_db,
        api_key=args.api_key,
        vector_dim=args.vector_dim,
        batch=args.batch,
    )

    if not args.query:
        print(json.dumps({"status": "ok", "message": "runtime ready", "embedder_enabled": runtime["embedder_enabled"]}, ensure_ascii=False))
        return

    result = run_query(runtime, text=args.query, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
