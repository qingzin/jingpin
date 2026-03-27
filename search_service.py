"""search_service.py
后端检索服务（供网页前端调用）。
- GET /health
- POST /search
- GET /download?path=...
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from wsgiref.simple_server import make_server

from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import BGEEmbedder
from core.query_parser import infer_target_component
from core.search_engine import QueryFilter, SearchEngine, SearchQuery


def json_response(start_response, status_code: int, data: dict):
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    start_response(f"{status_code} OK", [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def decode_request_json(raw_body: bytes) -> dict:
    """兼容 Windows/MINGW 下 curl 可能提交的非 UTF-8 请求体。"""
    if not raw_body:
        return {}
    last_error = None
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            text = raw_body.decode(encoding)
            return json.loads(text or "{}")
        except Exception as e:  # noqa: PERF203 - 逐编码尝试是预期流程
            last_error = e
    raise ValueError(f"无法解析请求体编码: {last_error}")


def app_factory(engine: SearchEngine, pointcloud_root: str):
    root_abs = os.path.abspath(pointcloud_root) if pointcloud_root else ""

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET").upper()

        if method == "GET" and path == "/health":
            return json_response(start_response, 200, {"status": "ok", "semantic_enabled": engine.embedder is not None})

        if method == "POST" and path == "/search":
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
                body = environ["wsgi.input"].read(length) if length else b"{}"
                payload = decode_request_json(body)
                text = (payload.get("query") or "").strip()
                top_k = int(payload.get("top_k", 20))
                filters = []
                for key, value in (payload.get("filters") or {}).items():
                    if value is None or value == "":
                        continue
                    filters.append(QueryFilter(field=str(key), op="=", value=value))

                if not text:
                    return json_response(start_response, 400, {"error": "query 不能为空"})

                if engine.embedder is not None:
                    query = SearchQuery(
                        semantic_query=text,
                        target_component=infer_target_component(text),
                        filters=filters,
                        top_k=top_k,
                        strategy="semantic_first",
                    )
                    response = engine.search(query)
                    rows = []
                    for item in response["result"]["results"]:
                        row = item["row"]
                        pc_path = row.get("pointcloud_path")
                        rows.append({
                            "rank": item.get("rank"),
                            "score": item.get("score"),
                            "part_name": row.get("part_name"),
                            "vehicle_name": row.get("source_file"),
                            "record_type": row.get("record_type") or "bom_part",
                            "part_number": row.get("part_number"),
                            "material": row.get("material"),
                            "level_path": " > ".join(row.get("level_array") or []),
                            "pointcloud_path": pc_path,
                            "pointcloud_download_url": f"/download?path={urllib.parse.quote(pc_path)}" if pc_path else None,
                        })
                    return json_response(start_response, 200, {
                        "mode": "semantic_or_fallback",
                        "top_k": top_k,
                        "total": len(rows),
                        "results": rows,
                    })

                # fallback: no embedder
                sql = """
                SELECT id, source_file, part_name, part_number, material, level_array, pointcloud_path, record_type
                FROM parts
                WHERE part_name ILIKE ?
                ORDER BY id DESC
                LIMIT ?
                """
                rows_db = engine.duck_store.conn.execute(sql, [f"%{text}%", top_k]).fetchall()
                rows = []
                for idx, row in enumerate(rows_db, start=1):
                    _, source_file, part_name, part_number, material, level_array, pc_path, record_type = row
                    rows.append({
                        "rank": idx,
                        "score": None,
                        "part_name": part_name,
                        "vehicle_name": source_file,
                        "record_type": record_type or "bom_part",
                        "part_number": part_number,
                        "material": material,
                        "level_path": " > ".join(level_array or []),
                        "pointcloud_path": pc_path,
                        "pointcloud_download_url": f"/download?path={urllib.parse.quote(pc_path)}" if pc_path else None,
                    })
                return json_response(start_response, 200, {
                    "mode": "fallback_keyword",
                    "top_k": top_k,
                    "total": len(rows),
                    "results": rows,
                })
            except Exception as e:
                return json_response(start_response, 500, {"error": str(e)})

        if method == "GET" and path == "/download":
            query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
            encoded = (query.get("path") or [""])[0]
            target = urllib.parse.unquote(encoded)
            if not target:
                return json_response(start_response, 400, {"error": "missing path"})
            abs_path = os.path.abspath(target)
            if root_abs and not abs_path.startswith(root_abs):
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
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--model", default="bge-m3")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--pointcloud-root", default="")
    args = parser.parse_args()

    duck = DuckDBStore(args.db)
    duck.init_schema()
    qdrant = QdrantStore(args.qdrant)
    qdrant.init_collection(dim=1024)

    embedder = None
    if args.api_key:
        embedder = BGEEmbedder(api_key=args.api_key, model=args.model)

    engine = SearchEngine(duck_store=duck, qdrant_store=qdrant, embedder=embedder)
    app = app_factory(engine, args.pointcloud_root)
    with make_server(args.host, args.port, app) as httpd:
        print(f"search service listening on http://{args.host}:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
