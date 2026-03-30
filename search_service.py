"""search_service.py
后端检索服务（供网页前端调用）。

提供与历史 Streamlit 交互功能一致的后端能力：
- GET /health
- GET /fields
- POST /search           结构化查询（强制语义检索）
- POST /search/nl        自然语言查询（可选 LLM）
- GET /download?path=...
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
import urllib.parse
from wsgiref.simple_server import make_server

from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import BGEEmbedder
from core.query_parser import NaturalLanguagePlanner, infer_target_component
from core.search_engine import QueryFilter, SearchEngine, SearchQuery
from core.search_presenter import present_results


def json_response(start_response, status_code: int, data: dict):
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    start_response(
        f"{status_code} OK",
        [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]


def _format_query(query: SearchQuery) -> str:
    parts = []
    if query.semantic_query:
        parts.append(f'semantic="{query.semantic_query}"')
    for f in query.filters:
        parts.append(f"{f.field}{f.op}{f.value}")
    parts.append(f"top={query.top_k}")
    return " ".join(parts)


def _parse_filters(payload_filters) -> list[QueryFilter]:
    filters: list[QueryFilter] = []
    if isinstance(payload_filters, dict):
        for key, value in payload_filters.items():
            if value is None or value == "":
                continue
            filters.append(QueryFilter(field=str(key), op="=", value=value))
        return filters

    if isinstance(payload_filters, list):
        for item in payload_filters:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            op = str(item.get("op") or "=").strip()
            value = item.get("value")
            if not field or value in (None, ""):
                continue
            filters.append(QueryFilter(field=field, op=op, value=value))
    return filters


def _make_response_payload(search_response: dict) -> dict:
    result = search_response["result"]
    display = present_results(result["results"], search_response["query"].filters)
    rows = []
    for item in result["results"]:
        row = item["row"]
        pc_path = row.get("pointcloud_path")
        level_path = " > ".join(row.get("level_array") or [])
        rows.append({
            "rank": item.get("rank"),
            "score": item.get("score"),
            "part_name": row.get("part_name"),
            "vehicle_name": row.get("source_file"),
            "record_type": row.get("record_type") or "bom_part",
            "part_number": row.get("part_number"),
            "material": row.get("material"),
            "process": row.get("process"),
            "weight_kg": row.get("weight_kg"),
            "length_mm": row.get("length_mm"),
            "width_mm": row.get("width_mm"),
            "height_mm": row.get("height_mm"),
            "depth_mm": row.get("depth_mm"),
            "level_path": level_path,
            "pointcloud_path": pc_path,
            "pointcloud_download_url": f"/download?path={urllib.parse.quote(pc_path)}" if pc_path else None,
        })

    return {
        "mode": "semantic",
        "strategy": search_response["strategy"],
        "elapsed_ms": result["elapsed_ms"],
        "candidate_count": result["candidate_count"],
        "retrieval_mode": result.get("retrieval_mode"),
        "retrieval_explanation": result.get("retrieval_explanation"),
        "notes": [*search_response["notes"], *result["notes"]],
        "parsed_query": _format_query(search_response["query"]),
        "query": {
            "semantic_query": search_response["query"].semantic_query,
            "target_component": search_response["query"].target_component,
            "top_k": search_response["query"].top_k,
            "filters": [asdict(f) for f in search_response["query"].filters],
        },
        "display": display,
        "total": len(rows),
        "results": rows,
    }


def _read_json_body(environ) -> dict:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(length) if length else b"{}"
    return json.loads(body.decode("utf-8") or "{}")


def _is_path_allowed(target: str, root_abs: str) -> bool:
    if not root_abs:
        return True
    try:
        return os.path.commonpath([os.path.abspath(target), root_abs]) == root_abs
    except ValueError:
        return False


def app_factory(engine: SearchEngine, planner: NaturalLanguagePlanner | None, pointcloud_root: str):
    root_abs = os.path.abspath(pointcloud_root) if pointcloud_root else ""

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET").upper()

        if method == "GET" and path == "/health":
            llm_enabled = bool(
                planner and planner.api_base and planner.api_key and planner.model
            )
            return json_response(
                start_response,
                200,
                {
                    "status": "ok",
                    "semantic_enabled": engine.embedder is not None,
                    "nl_enabled": bool(planner and engine.embedder is not None),
                    "llm_enabled": llm_enabled,
                },
            )

        if method == "GET" and path == "/fields":
            return json_response(start_response, 200, {"fields": engine.supported_fields()})

        if method == "POST" and path == "/search":
            try:
                payload = _read_json_body(environ)
                text = (payload.get("query") or "").strip()
                top_k = int(payload.get("top_k", 20))
                filters = _parse_filters(payload.get("filters"))

                if not text:
                    return json_response(start_response, 400, {"error": "query 不能为空"})
                if engine.embedder is None:
                    return json_response(start_response, 503, {"error": "服务未正确初始化：缺少 embedding 配置。"})

                query = SearchQuery(
                    semantic_query=text,
                    target_component=infer_target_component(text),
                    filters=filters,
                    top_k=top_k,
                    strategy="semantic_first",
                )
                response = engine.search(query)
                response_payload = _make_response_payload(response)
                return json_response(start_response, 200, response_payload)
            except Exception as e:
                return json_response(start_response, 500, {"error": str(e)})

        if method == "POST" and path == "/search/nl":
            if planner is None:
                return json_response(start_response, 400, {"error": "nl planner 未启用"})
            try:
                payload = _read_json_body(environ)
                text = (payload.get("query") or "").strip()
                top_k = int(payload.get("top_k", 20))
                if not text:
                    return json_response(start_response, 400, {"error": "query 不能为空"})
                if engine.embedder is None:
                    return json_response(start_response, 400, {"error": "当前未配置 embedding API key，无法执行自然语言语义检索。"})

                planned = planner.plan(text)
                planned.query.top_k = top_k
                planned.query.target_component = infer_target_component(planned.query.semantic_query)
                response = engine.search(planned.query)
                data = _make_response_payload(response)
                data["planner_notes"] = planned.notes
                data["unsupported_requirements"] = planned.unsupported_requirements
                return json_response(start_response, 200, data)
            except Exception as e:
                return json_response(start_response, 500, {"error": str(e)})

        if method == "GET" and path == "/download":
            query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
            encoded = (query.get("path") or [""])[0]
            target = urllib.parse.unquote(encoded)
            if not target:
                return json_response(start_response, 400, {"error": "missing path"})
            abs_path = os.path.abspath(target)
            if not _is_path_allowed(abs_path, root_abs):
                return json_response(start_response, 403, {"error": "path not allowed"})
            if not os.path.isfile(abs_path):
                return json_response(start_response, 404, {"error": "file not found"})
            with open(abs_path, "rb") as f:
                data = f.read()
            filename = os.path.basename(abs_path)
            start_response("200 OK", [
                ("Content-Type", "application/octet-stream"),
                ("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"),
                ("Content-Length", str(len(data))),
            ])
            return [data]

        return json_response(start_response, 404, {"error": "not found"})

    return app


def main():
    parser = argparse.ArgumentParser(description="Search backend service")
    parser.add_argument("--db", required=True)
    parser.add_argument("--qdrant", required=True)
    parser.add_argument("--api-key", required=True, help="Embedding API Key（必填）")
    parser.add_argument("--model", default="bge-m3")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--pointcloud-root", default="")
    parser.add_argument("--llm-api-base", default=None)
    parser.add_argument("--llm-api-key", default=None)
    parser.add_argument("--llm-model", default=None)
    args = parser.parse_args()

    duck = DuckDBStore(args.db)
    duck.init_schema()
    qdrant = QdrantStore(args.qdrant)
    qdrant.init_collection(dim=1024)

    embedder = BGEEmbedder(api_key=args.api_key, model=args.model)
    planner = NaturalLanguagePlanner(
        api_base=args.llm_api_base,
        api_key=args.llm_api_key,
        model=args.llm_model,
    )
    engine = SearchEngine(duck_store=duck, qdrant_store=qdrant, embedder=embedder)
    app = app_factory(engine, planner, args.pointcloud_root)
    with make_server(args.host, args.port, app) as httpd:
        print(f"search service listening on http://{args.host}:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
