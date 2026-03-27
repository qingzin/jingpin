import io
import json
import tempfile
from wsgiref.util import setup_testing_defaults

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
    def __init__(self, duck_store):
        self.duck_store = duck_store
        self.embedder = None


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


def test_search_service_keyword_fallback_returns_download_link(tmp_path):
    db_path = tmp_path / "parts.duckdb"
    duck = DuckDBStore(db_path)
    duck.init_schema()
    duck.insert_rows([
        {
            "source_file": "Tesla_Model3.xlsx",
            "source_row": 0,
            "part_name": "前门铰链上",
            "record_type": "bom_part",
            "pointcloud_path": "D:/pcd/Tesla_Model3/前门铰链上.stl",
            "level_array": ["车身系统", "车门总成"],
            "embedding_text": "前门铰链上 | 车身系统 > 车门总成",
            "raw_data": {},
            "form": "B",
        }
    ])

    app = app_factory(DummyEngine(duck), pointcloud_root="")

    payload = json.dumps({"query": "铰链", "top_k": 5}).encode("utf-8")
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "POST"
    environ["PATH_INFO"] = "/search"
    environ["CONTENT_LENGTH"] = str(len(payload))
    environ["wsgi.input"] = io.BytesIO(payload)

    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app(environ, start_response))
    data = json.loads(body.decode("utf-8"))

    assert captured["status"].startswith("200")
    assert data["mode"] == "fallback_keyword"
    assert data["total"] == 1
    assert data["results"][0]["pointcloud_download_url"].startswith("/download?path=")


def test_search_service_accepts_gbk_encoded_request_body(tmp_path):
    db_path = tmp_path / "parts.duckdb"
    duck = DuckDBStore(db_path)
    duck.init_schema()
    duck.insert_rows([
        {
            "source_file": "BYD_Han.xlsx",
            "source_row": 0,
            "part_name": "发动机总成",
            "record_type": "bom_part",
            "pointcloud_path": None,
            "level_array": ["动力系统", "发动机总成"],
            "embedding_text": "发动机总成 | 动力系统 > 发动机总成",
            "raw_data": {},
            "form": "B",
        }
    ])

    app = app_factory(DummyEngine(duck), pointcloud_root="")

    payload = json.dumps({"query": "发动机总成", "top_k": 5}, ensure_ascii=False).encode("gbk")
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "POST"
    environ["PATH_INFO"] = "/search"
    environ["CONTENT_LENGTH"] = str(len(payload))
    environ["wsgi.input"] = io.BytesIO(payload)

    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(app(environ, start_response))
    data = json.loads(body.decode("utf-8"))
    assert captured["status"].startswith("200")
    assert data["total"] == 1
    assert data["results"][0]["part_name"] == "发动机总成"
