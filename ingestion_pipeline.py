"""
ingestion_pipeline.py
主 Pipeline：从单张表到批量文件的完整 ingestion 流程。
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional
import pandas as pd
from tqdm import tqdm

from core.column_normalizer import ColumnNormalizer
from core.form_detector     import process_structure, structure_summary
from core.embedder          import BGEEmbedder, build_embedding_text, build_qdrant_payload
from core.db_duckdb         import DuckDBStore
from core.db_qdrant         import QdrantStore

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt = "%H:%M:%S",
)
logger = logging.getLogger(__name__)


def derive_vehicle_name_from_filename(file_name: str) -> str:
    """
    从 BOM 文件名提取车型名。

    约定：文件名形如“明细表_车型名.xlsx/csv”，提取下划线后的车型名。
    若不满足该结构，则回退为去扩展名后的 stem。
    """
    stem = Path(file_name).stem.strip()
    if stem.startswith("明细表_") and len(stem) > len("明细表_"):
        return stem.split("明细表_", 1)[1].strip()
    return stem


# ─────────────────────────────────────────────────────────────────────────────
# 配置默认值
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "mapping_path":   "config/column_mapping.json",
    "duckdb_path":    "db/bom.duckdb",
    "qdrant_path":    "db/qdrant_storage",
    "vector_dim":     1024,
    "embed_batch":    32,
    "insert_batch":   500,
    "header_candidate_rows": (0, 1),
    "drop_unnamed_cols": False,
}


# ─────────────────────────────────────────────────────────────────────────────
# 读取文件
# ─────────────────────────────────────────────────────────────────────────────

def read_file(
    file_path: str | Path,
    sheet_name=0,
    header_row: int = 0,
    drop_unnamed_cols: bool = False,
) -> pd.DataFrame:
    """
    读取 Excel (.xlsx/.xls) 或 CSV 文件。
    返回 DataFrame，所有列保留为字符串（避免 pandas 自动类型转换干扰列名识别）。
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet_name, header=header_row, dtype=str)
    elif suffix == ".csv":
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", header=header_row)
    else:
        raise ValueError(f"不支持的文件格式：{suffix}")

    # 清洗列名：去除首尾空格、换行符
    cleaned_cols = []
    unnamed_cols = []
    unnamed_count = 0
    for c in df.columns:
        c = str(c).strip().replace("\n", " ").replace("\r", " ")
        c = re.sub(r"\s+", " ", c).strip()
        if not c or c.lower().startswith("unnamed"):
            unnamed_count += 1
            c = f"_unnamed_{unnamed_count}"
            unnamed_cols.append(c)
        cleaned_cols.append(c)
    df.columns = cleaned_cols

    if drop_unnamed_cols and unnamed_cols:
        df = df.drop(columns=unnamed_cols, errors="ignore")

    # 删除全空行
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    logger.info(f"读取文件 {path.name}：{len(df)} 行，{len(df.columns)} 列")
    return df


def detect_header_row(
    file_path: str | Path,
    normalizer: ColumnNormalizer,
    sheet_name=0,
    candidate_rows: tuple[int, int] = (0, 1),
    unnamed_ratio_threshold: float = 0.4,
) -> tuple[int, dict]:
    """
    在候选表头行中选择质量最高的一行（默认第1/2行）。
    评分规则：
      score = recognized_cols + 2*level_col_count - unnamed_penalty
    当 unnamed 比例过高时额外惩罚，帮助识别“第一行不是表头”的场景。
    """
    best_row = candidate_rows[0]
    best_score = float("-inf")
    best_meta = {}

    for row in candidate_rows:
        try:
            df = read_file(file_path, sheet_name=sheet_name, header_row=row, drop_unnamed_cols=False)
            total_cols = max(1, len(df.columns))
            unnamed_cols = [c for c in df.columns if str(c).startswith("_unnamed_")]
            unnamed_ratio = len(unnamed_cols) / total_cols
            _, meta = normalizer.normalize(df)
            recognized = total_cols - len(meta["unmapped"]) - len(unnamed_cols)
            level_hits = len(meta["level_cols"])
            penalty = 0
            if unnamed_ratio > unnamed_ratio_threshold:
                penalty += int(unnamed_ratio * 10)
            score = recognized + 2 * level_hits - penalty
            if score > best_score:
                best_score = score
                best_row = row
                best_meta = {
                    "score": score,
                    "recognized_cols": recognized,
                    "level_hits": level_hits,
                    "unnamed_ratio": round(unnamed_ratio, 3),
                    "total_cols": total_cols,
                }
        except Exception as e:
            logger.warning(f"表头候选检测失败: file={file_path}, row={row}, err={e}")

    return best_row, best_meta


# ─────────────────────────────────────────────────────────────────────────────
# 单文件处理
# ─────────────────────────────────────────────────────────────────────────────

def process_single_file(
    file_path:   str | Path,
    normalizer:  ColumnNormalizer,
    embedder:    Optional[BGEEmbedder],
    duck_store:  DuckDBStore,
    qd_store:    QdrantStore,
    sheet_name   = 0,
    header_row: int = 0,
    drop_unnamed_cols: bool = False,
) -> dict:
    """
    完整处理单张表：
      读取 → 列名归一化 → 形态识别 → 层级重建 → 写 DuckDB → 生成 embedding → 写 Qdrant

    返回处理摘要 dict。
    """
    file_path = Path(file_path)
    t0 = time.time()

    # ── 1. 读取 ───────────────────────────────────────────────────────────────
    df = read_file(
        file_path,
        sheet_name=sheet_name,
        header_row=header_row,
        drop_unnamed_cols=drop_unnamed_cols,
    )
    original_cols = list(df.columns)

    # ── 2. 列名归一化 ─────────────────────────────────────────────────────────
    df, col_meta = normalizer.normalize(df)
    level_cols   = col_meta["level_cols"]   # [(level_0, 0), ...]
    unmapped     = col_meta["unmapped"]

    if unmapped:
        logger.info(f"  未识别列（{len(unmapped)} 个）: {unmapped[:10]}{'...' if len(unmapped)>10 else ''}")

    # ── 3. 形态识别 + 层级重建 ─────────────────────────────────────────────────
    df = process_structure(df, level_cols)
    source_vehicle_name = derive_vehicle_name_from_filename(file_path.name)
    summary = structure_summary(df, str(file_path.name))
    logger.info(
        f"  形态={summary['form']} | "
        f"名称 direct={summary['name_direct']} "
        f"derived={summary['name_derived']} "
        f"missing={summary['name_missing']}"
    )

    # ── 4. 构造入库行 ──────────────────────────────────────────────────────────
    rows_for_duck = []
    for row_idx, (_, row) in enumerate(df.iterrows()):
        row_dict = row.to_dict()

        # 保留原始行数据（去掉内部 _ 前缀的工作列）
        raw_data = {
            k: v for k, v in row_dict.items()
            if not k.startswith("_")
        }

        embed_text = build_embedding_text(row_dict)

        duck_row = {
            "source_file":     source_vehicle_name,
            "source_row":      row_idx,
            "part_name":       row_dict.get("_part_name"),
            "part_name_source":row_dict.get("_name_source"),
            "name_confidence": row_dict.get("_name_confidence"),
            "form":            row_dict.get("_form"),
            "level_array":     row_dict.get("_level_array"),
            "part_number":     row_dict.get("part_number"),
            "vehicle_model":   row_dict.get("vehicle_model"),
            "manufacturer":    row_dict.get("manufacturer"),
            "record_type":     "bom_part",
            "pointcloud_path": None,
            "material":        row_dict.get("material"),
            "material_code":   row_dict.get("material_code"),
            "material_type":   row_dict.get("material_type"),
            "material_grade":  row_dict.get("material_grade"),
            "surface_treat":   row_dict.get("surface_treat"),
            "process":         row_dict.get("process"),
            "weight_kg":       row_dict.get("weight_kg"),
            "total_weight_kg": row_dict.get("total_weight_kg"),
            "quantity":        row_dict.get("quantity"),
            "width_mm":        row_dict.get("width_mm"),
            "height_mm":       row_dict.get("height_mm"),
            "depth_mm":        row_dict.get("depth_mm"),
            "length_mm":       row_dict.get("length_mm"),
            "thickness_mm":    row_dict.get("thickness_mm"),
            "diameter_mm":     row_dict.get("diameter_mm"),
            "fastener_weight_kg": row_dict.get("fastener_weight_kg"),
            "fastener_spec":   row_dict.get("fastener_spec"),
            "fastener_grade":  row_dict.get("fastener_grade"),
            "fastener_color":  row_dict.get("fastener_color"),
            "tightening_torque_nm": row_dict.get("tightening_torque_nm"),
            "loosening_torque_nm":  row_dict.get("loosening_torque_nm"),
            "torque_location": row_dict.get("torque_location"),
            "location":        row_dict.get("location"),
            "detail":          row_dict.get("detail"),
            "remarks":         row_dict.get("remarks"),
            "aux_name":        row_dict.get("aux_name"),
            "part_type":       row_dict.get("part_type"),
            "seq_no":          row_dict.get("seq_no"),
            "teardown_date":   row_dict.get("teardown_date"),
            "a2mac1_ref":      row_dict.get("a2mac1_ref"),
            "left_desc":       row_dict.get("left_desc"),
            "right_desc":      row_dict.get("right_desc"),
            "rear_desc":       row_dict.get("rear_desc"),
            "system":          row_dict.get("system"),
            "nav_node_id":     row_dict.get("nav_node_id"),
            "navigation":      row_dict.get("navigation"),
            "site":            row_dict.get("site"),
            "print_flag":      row_dict.get("print_flag"),
            "assembly_teardown": row_dict.get("assembly_teardown"),
            "embedding_text":  embed_text,
            "raw_data":        raw_data,
        }
        rows_for_duck.append(duck_row)

    # ── 5. 写入 DuckDB ────────────────────────────────────────────────────────
    duck_store.insert_rows(rows_for_duck)

    # ── 6. 获取刚插入的 id（按 source_file + source_row 对齐）─────────────────
    id_df = duck_store.conn.execute(
        "SELECT id, source_row FROM parts WHERE source_file = ? ORDER BY source_row",
        [source_vehicle_name]
    ).df()
    id_map = dict(zip(id_df["source_row"], id_df["id"]))

    # ── 7. 生成 Embedding + 写入 Qdrant ───────────────────────────────────────
    if embedder is not None:
        texts      = [r["embedding_text"] for r in rows_for_duck]
        row_ids    = list(range(len(rows_for_duck)))

        logger.info(f"  生成 embedding：{len(texts)} 条...")
        vectors = embedder.embed(texts)

        qdrant_points = []
        for row_idx, vec in zip(row_ids, vectors):
            db_id = id_map.get(row_idx)
            if db_id is None:
                continue
            row = rows_for_duck[row_idx]
            qdrant_points.append({
                "id":     int(db_id),
                "vector": vec,
                "payload": build_qdrant_payload(row),
            })

        qd_store.upsert_vectors(qdrant_points)
    else:
        logger.warning("  embedder=None，跳过向量写入（仅 DuckDB 结构化数据）")

    elapsed = time.time() - t0
    summary["elapsed_sec"] = round(elapsed, 1)
    summary["unmapped_cols"] = unmapped
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 批量文件处理
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    file_paths:  list[str | Path],
    api_key:     Optional[str] = None,
    config:      dict = None,
) -> list[dict]:
    """
    批量 ingestion 入口。

    file_paths : 要处理的文件列表
    api_key    : BGE API Bearer Token（或通过环境变量 BGE_API_KEY 提供）
    config     : 覆盖默认配置项

    返回每个文件的处理摘要列表。
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    # ── 初始化组件 ─────────────────────────────────────────────────────────────
    normalizer = ColumnNormalizer(cfg["mapping_path"])

    # DuckDB
    duck_store = DuckDBStore(cfg["duckdb_path"])
    duck_store.init_schema()

    # Qdrant
    qd_store = QdrantStore(cfg["qdrant_path"])

    # Embedder（可选，如果 api_key 为空则跳过向量部分）
    embedder = None
    if api_key:
        embedder = BGEEmbedder(api_key=api_key, batch_size=cfg["embed_batch"])
        dim = cfg["vector_dim"]
        qd_store.init_collection(dim=dim)
        logger.info(f"Embedder 初始化完成，向量维度={dim}")
    else:
        logger.warning("未提供 api_key，向量检索功能不可用，仅写入结构化数据")

    # ── 逐文件处理 ─────────────────────────────────────────────────────────────
    all_summaries = []
    for fp in tqdm(file_paths, desc="处理文件", unit="file"):
        logger.info(f"\n{'='*60}\n处理文件：{fp}")
        try:
            header_row, header_meta = detect_header_row(
                fp,
                normalizer=normalizer,
                candidate_rows=tuple(cfg.get("header_candidate_rows", (0, 1))),
            )
            logger.info(f"  选定表头行: {header_row} | meta={header_meta}")
            summary = process_single_file(
                file_path  = fp,
                normalizer = normalizer,
                embedder   = embedder,
                duck_store = duck_store,
                qd_store   = qd_store,
                header_row = header_row,
                drop_unnamed_cols = bool(cfg.get("drop_unnamed_cols", False)),
            )
            summary["status"] = "ok"
        except Exception as e:
            logger.error(f"处理失败：{fp} → {e}", exc_info=True)
            summary = {"source_file": str(fp), "status": "error", "error": str(e)}

        all_summaries.append(summary)

    # ── 打印质量报告 ───────────────────────────────────────────────────────────
    logger.info("\n\n📊 数据质量报告：")
    report = duck_store.quality_report()
    print(report.to_string(index=False))

    duck_store.close()
    return all_summaries


# ─────────────────────────────────────────────────────────────────────────────
# 命令行入口
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, os

    parser = argparse.ArgumentParser(description="BOM 零部件 Ingestion Pipeline")
    parser.add_argument("files",      nargs="*", help="Excel/CSV 文件路径（可多个，与 --dir 二选一）")
    parser.add_argument("--dir",      default=None, help="扫描整个目录下所有 xlsx/xls/csv 文件")
    parser.add_argument("--api-key",  default=None, help="BGE API Bearer Token")
    parser.add_argument("--db",       default="db/bom.duckdb",     help="DuckDB 路径")
    parser.add_argument("--qdrant",   default="db/qdrant_storage", help="Qdrant 存储目录")
    parser.add_argument("--no-embed", action="store_true",         help="跳过 embedding，仅写结构化数据")
    args = parser.parse_args()

    # api_key 优先级：命令行 > 环境变量
    api_key = None if args.no_embed else (args.api_key or os.environ.get("BGE_API_KEY"))

    # ── 收集文件列表 ───────────────────────────────────────────────────────────
    file_list = []

    if args.dir:
        # --dir 模式：扫描目录，自动处理空格文件名
        scan_dir = Path(args.dir)
        if not scan_dir.is_dir():
            print(f"❌ 目录不存在：{scan_dir}")
            exit(1)
        for ext in ("*.xlsx", "*.xls", "*.csv"):
            file_list.extend(sorted(scan_dir.glob(ext)))
        if not file_list:
            print(f"❌ 目录下没有找到 xlsx/xls/csv 文件：{scan_dir}")
            exit(1)
        print(f"📂 扫描目录：{scan_dir}")
        print(f"   找到 {len(file_list)} 个文件：")
        for f in file_list:
            print(f"   - {f.name}")
        print()
    else:
        # 直接传文件路径模式
        from glob import glob
        for pattern in args.files:
            matched = glob(pattern)
            file_list.extend(matched if matched else [pattern])

    if not file_list:
        print("❌ 未指定任何文件，请使用文件路径或 --dir 目录参数")
        exit(1)

    summaries = run_pipeline(
        file_paths = file_list,
        api_key    = api_key,
        config     = {"duckdb_path": args.db, "qdrant_path": args.qdrant},
    )

    print("\n✅ 处理完成！摘要：")
    ok_count  = sum(1 for s in summaries if s.get("status") == "ok")
    err_count = sum(1 for s in summaries if s.get("status") == "error")
    for s in summaries:
        status  = s.get("status", "?")
        name    = s.get("source_file", "?")
        rows    = s.get("total_rows", "-")
        elapsed = s.get("elapsed_sec", "-")
        flag    = "✅" if status == "ok" else "❌"
        print(f"  {flag} {name:50s}  {rows} 行  {elapsed}s")
        if status == "error":
            print(f"     └─ 错误：{s.get('error')}")

    print(f"\n  共 {len(summaries)} 个文件：{ok_count} 成功，{err_count} 失败")
