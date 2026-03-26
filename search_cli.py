"""
search_cli.py
交互式 BOM 检索终端。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import BGEEmbedder
from core.query_cache import QueryEmbeddingCache
from core.query_parser import NaturalLanguagePlanner, parse_structured_query
from core.search_engine import SearchEngine

HELP_TEXT = """
命令:
  search ...            结构化搜索，例如:
                        search semantic="前门铰链" vehicle_name=Tesla_Model3_2022.xlsx surface_treat=电泳 weight_kg<=0.5 top=5
  nl ...                自然语言搜索，例如:
                        nl 查找 Model3 前门区域重量小于0.5kg 的铰链，表面处理为电泳
  fields                查看支持的筛选字段
  vehicles              查看上一轮结果命中的车型汇总
  show N                查看上一轮第 N 条结果的完整字段
  history               查看本次会话的查询历史
  export path.csv       导出上一轮结果
  help                  查看帮助
  quit / exit           退出
"""


class SearchCLI:
    def __init__(self, engine: SearchEngine, planner: NaturalLanguagePlanner):
        self.engine = engine
        self.planner = planner
        self.last_results: list[dict] = []
        self.history: list[str] = []

    def run(self):
        print("BOM Search CLI")
        print("输入 `help` 查看命令。")
        while True:
            try:
                line = input("bom-search> ").strip()
            except EOFError:
                print()
                break

            if not line:
                continue
            if line in {"quit", "exit"}:
                break
            self.history.append(line)

            try:
                self._handle_command(line)
            except Exception as e:
                print(f"❌ {e}")

    def run_once(self, command: str):
        self.history.append(command)
        self._handle_command(command)

    def _handle_command(self, line: str):
        if line == "help":
            print(HELP_TEXT)
            return
        if line == "fields":
            self._print_fields()
            return
        if line == "history":
            self._print_history()
            return
        if line == "vehicles":
            self._print_vehicle_summary("last", self.last_results)
            return
        if line.startswith("show "):
            self._show_result(line.split(maxsplit=1)[1])
            return
        if line.startswith("export "):
            self._export_results(line.split(maxsplit=1)[1])
            return
        if line.startswith("nl "):
            self._run_nl(line[3:].strip())
            return
        if line.startswith("search "):
            query = parse_structured_query(line)
            self._run_query(query)
            return

        # 允许用户直接输入筛选表达式或 semantic=...，默认当作 search 处理
        if any(op in line for op in ("semantic=", ">=", "<=", "=", ">", "<", "~")):
            query = parse_structured_query("search " + line)
            self._run_query(query)
            return

        print("❌ 未识别命令。输入 `help` 查看用法。")

    def _run_nl(self, text: str):
        planned = self.planner.plan(text)
        for note in planned.notes:
            print(f"note: {note}")
        if planned.unsupported_requirements:
            print("warning: 以下要求当前库里无法直接表达: " + ", ".join(planned.unsupported_requirements))
        print("parsed query:", self._format_query(planned.query))
        self._run_query(planned.query)

    def _run_query(self, query):
        response = self.engine.search(query)

        for note in response["notes"]:
            print(f"note: {note}")
        result = response["result"]
        for note in result["notes"]:
            print(f"note: {note}")
        print(f"strategy: {response['strategy']}, elapsed: {result['elapsed_ms']} ms, candidates: {result['candidate_count']}")
        self.last_results = result["results"]
        self._print_results_table(response["strategy"], result["results"])
        self._print_vehicle_summary(response["strategy"], result["results"])

    def _print_results_table(self, label: str, results: list[dict]):
        if not results:
            print(f"[{label}] no results")
            return

        rows = []
        for item in results:
            row = item["row"]
            level_array = self._normalize_level_array(row.get("level_array"))
            rows.append({
                "#": item["rank"],
                "score": item["score"],
                "vehicle": row.get("source_file"),
                "part_name": row.get("part_name"),
                "level_path": " > ".join(level_array),
                "weight_kg": row.get("weight_kg"),
                "material": row.get("material"),
                "surface_treat": row.get("surface_treat"),
                "soft_match": item.get("soft_match_score"),
            })
        df = pd.DataFrame(rows)
        print(f"[{label}]")
        print(df.to_string(index=False))

    def _print_vehicle_summary(self, label: str, results: list[dict]):
        if not results:
            return

        agg = {}
        for item in results:
            vehicle = item["row"].get("source_file") or "unknown"
            score = item["score"] if item["score"] is not None else 0.0
            part_name = item["row"].get("part_name")
            row = agg.setdefault(vehicle, {
                "vehicle": vehicle,
                "matched_parts": 0,
                "best_score": score,
                "example_part": part_name,
            })
            row["matched_parts"] += 1
            if score >= row["best_score"]:
                row["best_score"] = score
                row["example_part"] = part_name

        df = pd.DataFrame(sorted(agg.values(), key=lambda x: (x["best_score"], x["matched_parts"]), reverse=True))
        print(f"[{label} vehicles]")
        print(df.to_string(index=False))

    def _show_result(self, raw_index: str):
        if not self.last_results:
            print("没有可展示的结果。")
            return
        idx = int(raw_index) - 1
        if idx < 0 or idx >= len(self.last_results):
            print("结果序号超出范围。")
            return
        print(json.dumps(self.last_results[idx], ensure_ascii=False, indent=2, default=str))

    def _export_results(self, path_str: str):
        if not self.last_results:
            print("没有可导出的结果。")
            return

        path = Path(path_str)
        rows = []
        for item in self.last_results:
            row = dict(item["row"])
            row["score"] = item["score"]
            row["rank"] = item["rank"]
            rows.append(row)
        pd.DataFrame(rows).to_csv(path, index=False)
        print(f"已导出到 {path}")

    def _print_fields(self):
        df = pd.DataFrame(self.engine.supported_fields())
        print(df.to_string(index=False))

    def _print_history(self):
        if not self.history:
            print("history is empty")
            return
        for idx, item in enumerate(self.history, start=1):
            print(f"{idx:>2}. {item}")

    @staticmethod
    def _format_query(query) -> str:
        filter_parts = [f"{f.field}{f.op}{f.value}" for f in query.filters]
        base = f'semantic="{query.semantic_query}"' if query.semantic_query else "semantic=<empty>"
        return " ".join([base] + filter_parts + [f"top={query.top_k}", f"strategy={query.strategy}"])

    @staticmethod
    def _normalize_level_array(val):
        if val is None:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, tuple):
            return list(val)
        if hasattr(val, "tolist"):
            converted = val.tolist()
            if isinstance(converted, list):
                return converted
        return []


def build_cli(args) -> SearchCLI:
    duck_store = DuckDBStore(args.db)
    qdrant_store = QdrantStore(args.qdrant)
    qdrant_store.init_collection(dim=args.vector_dim)

    embedder = None
    api_key = args.api_key or os.environ.get("BGE_API_KEY")
    if api_key:
        embedder = BGEEmbedder(api_key=api_key, batch_size=args.batch)

    query_cache = QueryEmbeddingCache(args.cache_db)
    planner = NaturalLanguagePlanner(
        api_base=args.llm_api_base,
        api_key=args.llm_api_key,
        model=args.llm_model,
    )
    engine = SearchEngine(
        duck_store=duck_store,
        qdrant_store=qdrant_store,
        embedder=embedder,
        query_cache=query_cache,
    )
    return SearchCLI(engine=engine, planner=planner)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BOM interactive search CLI")
    parser.add_argument("--db", default="db/bom.duckdb", help="DuckDB 路径")
    parser.add_argument("--qdrant", default="db/qdrant_storage", help="Qdrant 存储路径")
    parser.add_argument("--cache-db", default="db/query_cache.duckdb", help="查询 embedding 缓存路径")
    parser.add_argument("--api-key", default="sk-kBP4BlJTUlhcaMVkfS2z7TIWlX7nVBnLtWRzDeHDG04mgOnM", help="BGE embedding API key")
    parser.add_argument("--vector-dim", type=int, default=1024, help="向量维度")
    parser.add_argument("--batch", type=int, default=8, help="查询 embedding 批大小")
    parser.add_argument("--llm-api-base", default="https://aiservice.byd.com/yicellm-api/v1", help="内网 LLM OpenAI-compatible base url")
    parser.add_argument("--llm-api-key", default="sk-kBP4BlJTUlhcaMVkfS2z7TIWlX7nVBnLtWRzDeHDG04mgOnM", help="内网 LLM API key")
    parser.add_argument("--llm-model", default="GPT-OSS-120B", help="内网 LLM model")
    parser.add_argument("--query", default=None, help="执行一条结构化查询后退出")
    parser.add_argument("--nl", default=None, help="执行一条自然语言查询后退出")
    args = parser.parse_args()

    cli = build_cli(args)
    if args.query:
        cli.run_once("search " + args.query)
    elif args.nl:
        cli.run_once("nl " + args.nl)
    else:
        cli.run()
