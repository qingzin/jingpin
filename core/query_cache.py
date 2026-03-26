"""
query_cache.py
缓存查询 embedding，避免工程师反复试探时重复调用 embedding API。
"""
import hashlib
import json
from pathlib import Path

import duckdb


class QueryEmbeddingCache:
    def __init__(self, db_path: str = "db/query_cache.duckdb"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS query_cache (
                cache_key   VARCHAR PRIMARY KEY,
                model       VARCHAR,
                query_text  VARCHAR,
                vector_json JSON
            )
        """)
        self.conn.commit()

    def get(self, query_text: str, model: str) -> list[float] | None:
        key = self._make_key(query_text, model)
        row = self.conn.execute(
            "SELECT vector_json FROM query_cache WHERE cache_key = ?",
            [key],
        ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def set(self, query_text: str, model: str, vector: list[float]):
        key = self._make_key(query_text, model)
        self.conn.execute("DELETE FROM query_cache WHERE cache_key = ?", [key])
        self.conn.execute(
            """
            INSERT INTO query_cache (cache_key, model, query_text, vector_json)
            VALUES (?, ?, ?, ?)
            """,
            [key, model, query_text, json.dumps(vector)],
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _make_key(query_text: str, model: str) -> str:
        base = f"{model}\n{query_text}".encode("utf-8")
        return hashlib.sha256(base).hexdigest()
