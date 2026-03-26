"""
test_search_product.py
验证单一路径检索：先语义召回，再做属性筛选。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import build_qdrant_payload
from core.query_expander import expand_filter_values, expand_text_query
from core.query_parser import NaturalLanguagePlanner, infer_target_component, parse_structured_query
from core.search_engine import QueryFilter, SearchEngine, SearchQuery


class FakeEmbedder:
    model = "fake-model"

    def embed_single(self, text: str):
        if "铰链" in text:
            return [1.0, 0.0]
        if "出风口" in text or "仪表盘" in text or "仪表板" in text:
            return [0.3, 0.7]
        if "加强板" in text or "前舱" in text or "固定件" in text:
            return [0.0, 1.0]
        if "引擎盖" in text:
            return [0.2, 0.8]
        return [0.5, 0.5]


def build_demo_env():
    tmpdir = tempfile.TemporaryDirectory()
    duck = DuckDBStore(f"{tmpdir.name}/parts.duckdb")
    duck.init_schema()
    qdrant = QdrantStore(f"{tmpdir.name}/qdrant")
    qdrant.init_collection(dim=2, recreate=True)

    rows = [
        {
            "source_file": "Tesla_Model3_2022.xlsx",
            "source_row": 0,
            "part_name": "前门铰链上",
            "part_number": "M3-H-001",
            "manufacturer": "麦格纳",
            "material": "钢",
            "surface_treat": "电泳",
            "weight_kg": 0.30,
            "level_array": ["车身系统", "车门总成", "前左门", "铰链"],
            "embedding_text": "前门铰链上 | 车身系统 > 车门总成 > 前左门 > 铰链",
            "form": "B",
            "raw_data": {},
        },
        {
            "source_file": "Tesla_Model3_2022.xlsx",
            "source_row": 1,
            "part_name": "前舱加强板",
            "part_number": "M3-R-001",
            "manufacturer": "本特勒",
            "material": "铝",
            "surface_treat": "阳极氧化",
            "weight_kg": 1.20,
            "level_array": ["车身系统", "前舱", "加强板"],
            "embedding_text": "前舱加强板 | 车身系统 > 前舱 > 加强板",
            "form": "B",
            "raw_data": {},
        },
        {
            "source_file": "Seal06_2024.xlsx",
            "source_row": 2,
            "part_name": "前门铰链下",
            "part_number": "S06-H-002",
            "manufacturer": "弗迪",
            "material": "钢",
            "surface_treat": "电泳",
            "weight_kg": 0.35,
            "level_array": ["车身系统", "车门总成", "前右门", "铰链"],
            "embedding_text": "前门铰链下 | 车身系统 > 车门总成 > 前右门 > 铰链",
            "form": "B",
            "raw_data": {},
        },
        {
            "source_file": "Han_2024.xlsx",
            "source_row": 3,
            "part_name": "引擎盖",
            "part_number": "HAN-HOOD-001",
            "manufacturer": "弗迪",
            "material": "铝",
            "surface_treat": "喷涂",
            "weight_kg": 12.0,
            "level_array": ["车身系统", "覆盖件", "引擎盖"],
            "embedding_text": "引擎盖 | 车身系统 > 覆盖件 > 引擎盖",
            "form": "B",
            "raw_data": {},
        },
    ]
    duck.insert_rows(rows)

    id_rows = duck.conn.execute("SELECT * FROM parts ORDER BY id").df()
    vectors = {
        "前门铰链上": [1.0, 0.0],
        "前舱加强板": [0.0, 1.0],
        "前门铰链下": [0.95, 0.05],
        "引擎盖": [0.2, 0.8],
    }
    points = []
    for _, row in id_rows.iterrows():
        row_dict = row.to_dict()
        points.append({
            "id": int(row_dict["id"]),
            "vector": vectors[row_dict["part_name"]],
            "payload": build_qdrant_payload(row_dict),
        })
    qdrant.upsert_vectors(points)

    engine = SearchEngine(duck_store=duck, qdrant_store=qdrant, embedder=FakeEmbedder())
    return tmpdir, duck, qdrant, engine


def build_alias_env():
    tmpdir = tempfile.TemporaryDirectory()
    duck = DuckDBStore(f"{tmpdir.name}/parts.duckdb")
    duck.init_schema()
    qdrant = QdrantStore(f"{tmpdir.name}/qdrant")
    qdrant.init_collection(dim=2, recreate=True)

    rows = [
        {
            "source_file": "a.xlsx",
            "source_row": 1,
            "part_name": "仪表板左侧出风口总成",
            "weight_kg": 0.2,
            "width_mm": 100,
            "height_mm": 80,
            "depth_mm": 70,
            "level_array": ["内饰", "仪表板", "左侧出风口总成"],
            "embedding_text": "仪表板左侧出风口总成 | 内饰 > 仪表板 > 左侧出风口总成",
            "form": "B",
            "raw_data": {},
        },
        {
            "source_file": "b.xlsx",
            "source_row": 2,
            "part_name": "Left",
            "weight_kg": 0.2,
            "width_mm": 90,
            "height_mm": 70,
            "depth_mm": 60,
            "level_array": ["Body", "Closures", "Left"],
            "embedding_text": "Left | Body > Closures > Left",
            "form": "B",
            "raw_data": {},
        },
    ]
    duck.insert_rows(rows)

    id_rows = duck.conn.execute("SELECT * FROM parts ORDER BY id").df()
    points = []
    for _, row in id_rows.iterrows():
        row_dict = row.to_dict()
        vector = [0.3, 0.7] if row_dict["part_name"] == "仪表板左侧出风口总成" else [0.1, 0.1]
        points.append({
            "id": int(row_dict["id"]),
            "vector": vector,
            "payload": build_qdrant_payload(row_dict),
        })
    qdrant.upsert_vectors(points)

    engine = SearchEngine(duck_store=duck, qdrant_store=qdrant, embedder=FakeEmbedder())
    return tmpdir, duck, qdrant, engine


def test_parse_structured_query():
    query = parse_structured_query(
        'search semantic="前门铰链" vehicle_name=Tesla_Model3_2022.xlsx surface_treat=电泳 weight_kg<=0.5 top=5'
    )
    assert query.semantic_query == "前门铰链"
    assert query.target_component == "前门铰链"
    assert query.top_k == 5
    assert len(query.filters) == 3
    assert query.filters[0].field == "vehicle_name"


def test_infer_target_component():
    assert infer_target_component("重量小于15kg的引擎盖") == "引擎盖"
    assert infer_target_component("查找前舱固定件") == "前舱固定件"
    assert infer_target_component("重量小于15kg的仪表板左侧出风口总成") == "仪表板左侧出风口总成"


def test_nl_target_component_is_not_duplicated():
    planner = NaturalLanguagePlanner(api_base=None, api_key=None, model=None)
    planned = planner.plan("宽高深都小于200的仪表盘左侧出风口总成")
    assert planned.query.target_component == "仪表盘左侧出风口总成"
    assert planned.query.semantic_query.count("仪表盘左侧出风口总成") == 1


def test_chinese_query_expansion():
    expanded = expand_text_query("仪表盘总成")
    assert "dashboard" in expanded.lower() or "instrument panel" in expanded.lower()

    values = expand_filter_values("钢")
    assert "steel" in [v.lower() for v in values]


def test_semantic_first_search_filters_after_recall():
    tmpdir, duck, qdrant, engine = build_demo_env()
    try:
        query = SearchQuery(
            semantic_query="前门铰链",
            filters=[
                QueryFilter("vehicle_name", "=", "Tesla_Model3_2022.xlsx"),
                QueryFilter("weight_kg", "<=", 0.31),
            ],
            top_k=50,
            strategy="semantic_first",
        )
        result = engine.search(query)
        rows = result["result"]["results"]
        assert rows
        assert len(rows) == 1
        assert rows[0]["row"]["part_name"] == "前门铰链上"
        assert result["strategy"] == "semantic_first"
        assert result["result"]["retrieval_mode"] == "semantic_then_filter"
    finally:
        duck.close()
        qdrant.close()
        tmpdir.cleanup()


def test_semantic_first_handles_target_alias_without_direct_hit_branch():
    tmpdir, duck, qdrant, engine = build_alias_env()
    try:
        query = SearchQuery(
            semantic_query="仪表盘左侧出风口总成",
            target_component="仪表盘左侧出风口总成",
            filters=[QueryFilter("weight_kg", "<=", 15)],
            top_k=50,
            strategy="semantic_first",
        )
        result = engine.search(query)
        rows = result["result"]["results"]
        assert rows
        assert rows[0]["row"]["part_name"] == "仪表板左侧出风口总成"
        assert result["result"]["retrieval_mode"] == "semantic_then_filter"
    finally:
        duck.close()
        qdrant.close()
        tmpdir.cleanup()


def test_semantic_first_empty_after_filter_shows_single_path_note():
    tmpdir, duck, qdrant, engine = build_demo_env()
    try:
        query = SearchQuery(
            semantic_query="前门铰链",
            filters=[QueryFilter("weight_kg", "<", 0.1)],
            top_k=20,
            strategy="semantic_first",
        )
        result = engine.search(query)
        assert result["result"]["results"] == []
        assert result["result"]["retrieval_mode"] == "empty"
        assert any("前 20 条候选里执行属性筛选" in note for note in result["result"]["notes"])
    finally:
        duck.close()
        qdrant.close()
        tmpdir.cleanup()


if __name__ == "__main__":
    test_parse_structured_query()
    test_infer_target_component()
    test_nl_target_component_is_not_duplicated()
    test_chinese_query_expansion()
    test_semantic_first_search_filters_after_recall()
    test_semantic_first_handles_target_alias_without_direct_hit_branch()
    test_semantic_first_empty_after_filter_shows_single_path_note()
    print("search product tests passed")
