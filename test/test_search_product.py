import io
import json
import tempfile
from wsgiref.util import setup_testing_defaults
from dataclasses import dataclass

from builder_tool import (
    PointCloudEntry,
    attach_pointcloud_path_to_part,
    find_part_id_by_vehicle_and_name,
    upsert_pointcloud_only,
)
from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from search_service import app_factory


class DummyEngine:
    def __init__(self, duck_store, with_embedder: bool = True):
        self.duck_store = duck_store
        self.embedder = object() if with_embedder else None

    @staticmethod
    def supported_fields():
        return [{"field": "vehicle_name", "type": "text", "ops": "=~"}]

    @staticmethod
    def search(query):
        return {
            "strategy": query.strategy,
            "notes": ["dummy search"],
            "query": query,
            "result": {
                "elapsed_ms": 3,
                "candidate_count": 1,
                "retrieval_mode": "vector",
                "retrieval_explanation": "dummy",
                "notes": [],
                "results": [
                    {
                        "rank": 1,
                        "score": 0.99,
                        "row": {
                            "source_file": "Tesla_Model3.xlsx",
                            "part_name": "前门铰链上",
                            "record_type": "bom_part",
                            "part_number": "PN-001",
                            "material": "steel",
                            "level_array": ["车身系统", "车门总成"],
                            "pointcloud_path": "D:/pcd/Tesla_Model3/前门铰链上.stl",
                        },
                    }
                ],
            },
        }


@dataclass
class DummyPlanned:
    query: object
    notes: list[str]
    unsupported_requirements: list[str]


class DummyPlanner:
    api_base = None
    api_key = None
    model = None

    def plan(self, text):
        from core.search_engine import SearchQuery
        return DummyPlanned(
            query=SearchQuery(semantic_query=text, target_component=text, filters=[], top_k=3, strategy="semantic_first"),
            notes=["rule planner used"],
            unsupported_requirements=[],
        )


def _invoke_app(app, method: str, path: str, payload: dict | None = None, query_string: str = ""):

    body = json.dumps(payload or {}).encode("utf-8")
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["wsgi.input"] = io.BytesIO(body)
    environ["QUERY_STRING"] = query_string
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    response_body = b"".join(app(environ, start_response))
    if not response_body:
        return captured["status"], {}
    return captured["status"], json.loads(response_body.decode("utf-8"))


def test_pointcloud_match_and_pointcloud_only_insert():
    with tempfile.TemporaryDirectory() as tmpdir:
        duck = DuckDBStore(f"{tmpdir}/parts.duckdb")
        duck.init_schema()
        qdrant = QdrantStore(f"{tmpdir}/qdrant")

        duck.insert_rows([
            {
                "source_file": "Tesla_Model3.xlsx",
                "source_row": 0,
                "part_name": "前门铰链上",
                "record_type": "bom_part",
                "level_array": ["车身系统", "车门总成"],
                "embedding_text": "前门铰链上 | 车身系统 > 车门总成",
                "raw_data": {},
                "form": "B",
            }
        ])

        matched_id = find_part_id_by_vehicle_and_name(
            duck,
            vehicle_key="teslamodel3",
            part_key="前门铰链上",
        )
        assert matched_id is not None

        attach_pointcloud_path_to_part(duck, matched_id, "D:/pcd/Tesla_Model3/前门铰链上.stl")
        path = duck.conn.execute("SELECT pointcloud_path FROM parts WHERE id=?", [matched_id]).fetchone()[0]
        assert path.endswith("前门铰链上.stl")

        entry = PointCloudEntry(
            vehicle_key="teslamodel3",
            vehicle_name="Tesla_Model3",
            pointcloud_name="前门铰链下",
            pointcloud_path="D:/pcd/Tesla_Model3/前门铰链下.obj",
        )
        new_id = upsert_pointcloud_only(duck, qdrant, embedder=None, entry=entry)
        row = duck.conn.execute(
            "SELECT record_type, part_name, pointcloud_path FROM parts WHERE id=?",
            [new_id],
        ).fetchone()
        assert row[0] == "pointcloud_only"
        assert row[1] == "前门铰链下"
        assert row[2].endswith("前门铰链下.obj")

        same_id = upsert_pointcloud_only(duck, qdrant, embedder=None, entry=entry)
        assert same_id == new_id
        cnt = duck.conn.execute(
            "SELECT COUNT(*) FROM parts WHERE source_file=? AND source_row=-1 AND part_name=? AND pointcloud_path=?",
            [entry.vehicle_name, entry.pointcloud_name, entry.pointcloud_path],
        ).fetchone()[0]
        assert cnt == 1


def test_search_service_returns_semantic_result_with_download_link(tmp_path):
    db_path = tmp_path / "parts.duckdb"
    duck = DuckDBStore(db_path)
    duck.init_schema()

    app = app_factory(DummyEngine(duck, with_embedder=True), planner=DummyPlanner(), pointcloud_root="")
    status, data = _invoke_app(app, "POST", "/search", {"query": "铰链", "top_k": 5})
    assert status.startswith("200")
    assert data["mode"] == "semantic"
    assert data["total"] == 1
    assert data["results"][0]["pointcloud_download_url"].startswith("/download?path=")


def test_search_service_fields_endpoint(tmp_path):
    duck = DuckDBStore(tmp_path / "parts.duckdb")
    duck.init_schema()
    app = app_factory(DummyEngine(duck, with_embedder=True), planner=DummyPlanner(), pointcloud_root="")
    status, data = _invoke_app(app, "GET", "/fields")
    assert status.startswith("200")
    assert isinstance(data["fields"], list)
    assert data["fields"][0]["field"] == "vehicle_name"


def test_search_service_requires_embedder_for_search(tmp_path):
    duck = DuckDBStore(tmp_path / "parts.duckdb")
    duck.init_schema()
    app = app_factory(DummyEngine(duck, with_embedder=False), planner=DummyPlanner(), pointcloud_root="")
    status, data = _invoke_app(app, "POST", "/search", {"query": "查找前门铰链", "top_k": 5})
    assert status.startswith("503")
    assert "embedding" in data["error"]


def test_search_service_nl_requires_embedder(tmp_path):
    duck = DuckDBStore(tmp_path / "parts.duckdb")
    duck.init_schema()
    app = app_factory(DummyEngine(duck, with_embedder=False), planner=DummyPlanner(), pointcloud_root="")
    status, data = _invoke_app(app, "POST", "/search/nl", {"query": "查找前门铰链", "top_k": 5})
    assert status.startswith("400")
    assert "embedding" in data["error"]


def test_search_service_health_has_cors_headers(tmp_path):
    duck = DuckDBStore(tmp_path / "parts.duckdb")
    duck.init_schema()
    app = app_factory(DummyEngine(duck, with_embedder=True), planner=DummyPlanner(), pointcloud_root="")
    status, _ = _invoke_app(app, "GET", "/health")
    assert status.startswith("200")

    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "GET"
    environ["PATH_INFO"] = "/health"
    environ["CONTENT_LENGTH"] = "0"
    environ["wsgi.input"] = io.BytesIO(b"")
    captured = {}

    def start_response(status_line, headers):
        captured["headers"] = {k.lower(): v for k, v in headers}

    _ = b"".join(app(environ, start_response))
    assert captured["headers"].get("access-control-allow-origin") == "*"


def test_search_service_options_preflight(tmp_path):
    duck = DuckDBStore(tmp_path / "parts.duckdb")
    duck.init_schema()
    app = app_factory(DummyEngine(duck, with_embedder=True), planner=DummyPlanner(), pointcloud_root="")
    status, _ = _invoke_app(app, "OPTIONS", "/health")
    assert status.startswith("204")
