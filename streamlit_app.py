"""
streamlit_app.py
本地运行的 BOM 检索 Streamlit 前端。
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
import streamlit as st

from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import BGEEmbedder
from core.query_cache import QueryEmbeddingCache
from core.query_parser import NaturalLanguagePlanner, infer_target_component
from core.search_engine import QueryFilter, SearchEngine, SearchQuery
from core.search_presenter import present_results


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", default="db/bom.duckdb")
    parser.add_argument("--qdrant", default="db/qdrant_storage")
    parser.add_argument("--cache-db", default="db/query_cache.duckdb")
    parser.add_argument("--api-key", default="sk-kBP4BlJTUlhcaMVkfS2z7TIWlX7nVBnLtWRzDeHDG04mgOnM")
    parser.add_argument("--vector-dim", type=int, default=1024)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--llm-api-base", default="https://aiservice.byd.com/yicellm-api/v1")
    parser.add_argument("--llm-api-key", default="sk-kBP4BlJTUlhcaMVkfS2z7TIWlX7nVBnLtWRzDeHDG04mgOnM")
    parser.add_argument("--llm-model", default="GPT-OSS-120B")
    args, _ = parser.parse_known_args(sys.argv[1:])
    return args


@st.cache_resource(show_spinner=False)
def build_runtime(
    db_path: str,
    qdrant_path: str,
    cache_db: str,
    api_key: str | None,
    vector_dim: int,
    batch: int,
    llm_api_base: str | None,
    llm_api_key: str | None,
    llm_model: str | None,
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
    planner = NaturalLanguagePlanner(
        api_base=llm_api_base,
        api_key=llm_api_key,
        model=llm_model,
    )
    engine = SearchEngine(
        duck_store=duck_store,
        qdrant_store=qdrant_store,
        embedder=embedder,
        query_cache=query_cache,
    )
    return {
        "engine": engine,
        "planner": planner,
        "embedder_enabled": embedder is not None,
        "llm_enabled": bool(planner.api_base and planner.api_key and planner.model),
    }


def format_query(query: SearchQuery) -> str:
    parts = []
    if query.semantic_query:
        parts.append(f'semantic="{query.semantic_query}"')
    for filter_obj in query.filters:
        parts.append(f"{filter_obj.field}{filter_obj.op}{filter_obj.value}")
    parts.append(f"top={query.top_k}")
    return " ".join(parts)


def build_filters(form_values: dict) -> list[QueryFilter]:
    mappings = [
        ("level_contains", "~", form_values["level_contains"]),
        ("weight_kg", "<=", form_values["weight_max"]),
        ("total_weight_kg", "<=", form_values["total_weight_max"]),
        ("length_mm", "<=", form_values["length_max"]),
        ("width_mm", "<=", form_values["width_max"]),
        ("height_mm", "<=", form_values["height_max"]),
        ("depth_mm", "<=", form_values["depth_max"]),
    ]

    filters = []
    for field, op, value in mappings:
        if value in (None, ""):
            continue
        filters.append(QueryFilter(field=field, op=op, value=value))
    return filters


def render_badges(runtime):
    badges = []
    badges.append("语义检索可用" if runtime["embedder_enabled"] else "未配置语义检索")
    badges.append("LLM 规划可用" if runtime["llm_enabled"] else "规则解析模式")
    cols = st.columns(len(badges))
    for idx, text in enumerate(badges):
        cols[idx].markdown(f"<div class='status-badge'>{text}</div>", unsafe_allow_html=True)


def render_notes(title: str, notes: list[str]):
    if not notes:
        return
    st.markdown(f"**{title}**")
    for note in notes:
        st.markdown(f"<div class='note-box'>{note}</div>", unsafe_allow_html=True)


def run_structured_search(runtime, form_values: dict):
    query = SearchQuery(
        semantic_query=form_values["semantic_query"].strip(),
        target_component=infer_target_component(form_values["semantic_query"]),
        filters=build_filters(form_values),
        top_k=int(form_values["top_k"]),
        strategy="semantic_first",
    )
    if not query.semantic_query and not query.target_component:
        raise ValueError("当前只保留语义优先路径，请填写目标件或目标描述。")
    if not runtime["embedder_enabled"]:
        raise ValueError("当前未配置 embedding API key，无法执行语义检索。请启动时传入 --api-key。")
    return execute_query(runtime["engine"], query)


def run_nl_search(runtime, text: str, top_k: int):
    if not text.strip():
        raise ValueError("自然语言查询不能为空。")
    planned = runtime["planner"].plan(text.strip())
    planned.query.top_k = int(top_k)
    if not planned.query.semantic_query and not planned.query.target_component:
        raise ValueError("自然语言里没有解析出明确的目标件或目标描述，请补充更具体的零部件名称。")
    if not runtime["embedder_enabled"]:
        raise ValueError("当前未配置 embedding API key，无法执行语义检索。请启动时传入 --api-key。")
    response = execute_query(runtime["engine"], planned.query)
    response["planner_notes"] = planned.notes
    response["unsupported_requirements"] = planned.unsupported_requirements
    response["parsed_query"] = format_query(planned.query)
    return response


def execute_query(engine: SearchEngine, query: SearchQuery) -> dict:
    response = engine.search(query)
    result = response["result"]
    display = present_results(result["results"], response["query"].filters)
    return {
        "strategy": response["strategy"],
        "elapsed_ms": result["elapsed_ms"],
        "candidate_count": result["candidate_count"],
        "retrieval_mode": result.get("retrieval_mode"),
        "retrieval_explanation": result.get("retrieval_explanation"),
        "results": result["results"],
        "display": display,
        "notes": [*response["notes"], *result["notes"]],
        "parsed_query": format_query(response["query"]),
        "planner_notes": [],
        "unsupported_requirements": [],
        "target_component": response["query"].target_component,
    }


def render_results(response: dict):
    st.markdown(
        f"**检索摘要**  `{response['strategy']}`  |  {response['elapsed_ms']} ms  |  候选 {response['candidate_count']}  |  返回 {len(response['results'])}"
    )
    if response.get("retrieval_mode"):
        target_suffix = f" | 目标件：{response['target_component']}" if response.get("target_component") else ""
        st.markdown(
            f"<div class='retrieval-card'><strong>检索解释</strong><br>{response.get('retrieval_explanation', '')}{target_suffix}</div>",
            unsafe_allow_html=True,
        )
    render_notes("提示", response.get("notes", []))
    render_notes("自然语言规划", response.get("planner_notes", []))

    unsupported = response.get("unsupported_requirements", [])
    if unsupported:
        st.warning("当前无法直接表达: " + "、".join(unsupported))

    if response.get("parsed_query"):
        st.code(response["parsed_query"], language="text")

    display = response["display"]
    rows = display["rows"]
    if rows:
        ordered_columns = [column["key"] for column in display.get("columns", [])]
        df = pd.DataFrame(rows)
        if ordered_columns:
            existing_columns = [column for column in ordered_columns if column in df.columns]
            trailing_columns = [column for column in df.columns if column not in existing_columns]
            df = df[existing_columns + trailing_columns]
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv_data = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "导出当前结果 CSV",
            data=csv_data,
            file_name="bom_search_results.csv",
            mime="text/csv",
        )
    else:
        st.info("没有结果。请尝试放宽条件或修改语义描述。")

    st.markdown("**命中车型**")
    vehicles = display["vehicle_summary"]
    if vehicles:
        vehicle_df = pd.DataFrame(vehicles)
        st.dataframe(vehicle_df, use_container_width=True, hide_index=True)
    else:
        st.caption("当前没有车型汇总。")


def inject_styles():
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #fbfbfc 0%, #f2f4f7 100%);
        }
        .block-container {
            max-width: 1280px;
            padding-top: 2rem;
            padding-bottom: 3rem;
        }
        .hero-card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 24px;
            padding: 24px 28px;
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.06);
            margin-bottom: 1rem;
        }
        .hero-card h1 {
            margin: 0;
            color: #111827;
            font-size: 2.4rem;
        }
        .hero-card p {
            margin: 0.75rem 0 0;
            color: #667085;
            line-height: 1.7;
        }
        .status-badge {
            background: #ffffff;
            border: 1px solid #dbe1ea;
            border-radius: 999px;
            padding: 10px 14px;
            text-align: center;
            color: #111827;
            font-size: 0.95rem;
        }
        .note-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 14px;
            padding: 10px 12px;
            margin-bottom: 8px;
            color: #334155;
        }
        .retrieval-card {
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #dbe1ea;
            border-radius: 18px;
            padding: 14px 16px;
            margin: 10px 0 16px;
            color: #0f172a;
            line-height: 1.6;
        }
        div[data-testid="stForm"] {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 22px;
            padding: 16px 16px 4px;
            box-shadow: 0 16px 36px rgba(15, 23, 42, 0.05);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    args = parse_args()
    st.set_page_config(page_title="BOM Search", page_icon="BOM", layout="wide")
    inject_styles()

    runtime = build_runtime(
        db_path=args.db,
        qdrant_path=args.qdrant,
        cache_db=args.cache_db,
        api_key=args.api_key,
        vector_dim=args.vector_dim,
        batch=args.batch,
        llm_api_base=args.llm_api_base,
        llm_api_key=args.llm_api_key,
        llm_model=args.llm_model,
    )

    st.markdown(
        """
        <div class="hero-card">
          <h1>竞品拆解件检索台</h1>
          <p>当前只保留单一路径：先用目标件或目标描述做语义召回，再对召回结果执行属性筛选。默认召回 100 条，可调小以提高速度。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_badges(runtime)

    if "last_response" not in st.session_state:
        st.session_state["last_response"] = None
    left_col, right_col = st.columns([1.15, 0.85], gap="large")

    with left_col:
        st.subheader("自然语言查询")
        with st.form("nl_form", clear_on_submit=False):
            nl_query = st.text_area(
                "直接描述你的需求",
                placeholder="例如：重量小于15kg的仪表盘左侧出风口总成",
                height=140,
            )
            nl_top_k = st.number_input("语义召回条数", min_value=1, max_value=1000, value=100, step=50)
            nl_submit = st.form_submit_button("自然语言搜索", use_container_width=True)
        if nl_submit:
            try:
                st.session_state["last_response"] = run_nl_search(runtime, nl_query, nl_top_k)
            except Exception as exc:
                st.session_state["last_response"] = {"error": str(exc)}

    with right_col:
        st.subheader("精准筛选")
        with st.form("structured_form", clear_on_submit=False):
            semantic_query = st.text_input("目标件或目标描述", placeholder="例如：仪表盘左侧出风口总成")
            level_contains = st.text_input("层级包含", placeholder="例如：车门总成 / 前舱")

            num_col1, num_col2 = st.columns(2)
            with num_col1:
                weight_max = st.text_input("重量上限(kg)")
                total_weight_max = st.text_input("总重量上限(kg)")
                length_max = st.text_input("长度上限(mm)")
            with num_col2:
                width_max = st.text_input("宽度上限(mm)")
                height_max = st.text_input("高度上限(mm)")
                depth_max = st.text_input("深度上限(mm)")
                top_k = st.number_input("语义召回条数", min_value=1, max_value=1000, value=100, step=50)

            structured_submit = st.form_submit_button("结构化搜索", use_container_width=True)

        if structured_submit:
            form_values = {
                "semantic_query": semantic_query,
                "level_contains": level_contains,
                "weight_max": weight_max,
                "total_weight_max": total_weight_max,
                "length_max": length_max,
                "width_max": width_max,
                "height_max": height_max,
                "depth_max": depth_max,
                "top_k": top_k,
            }
            try:
                st.session_state["last_response"] = run_structured_search(runtime, form_values)
            except Exception as exc:
                st.session_state["last_response"] = {"error": str(exc)}

    st.subheader("检索结果")
    response = st.session_state.get("last_response")
    if not response:
        st.info("提交查询后，结果会显示在这里。")
        return
    if response.get("error"):
        st.error(response["error"])
        return
    render_results(response)


if __name__ == "__main__":
    main()
