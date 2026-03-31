"""builder_tool.py
后端建库工具：
- 扫描 BOM 文件夹
- 自适应表头（第1/2行）
- 写入 DuckDB/Qdrant
- 扫描点云目录并做关联或 pointcloud_only 入库
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import yaml

from core.column_normalizer import ColumnNormalizer
from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import BGEEmbedder, build_qdrant_payload
from ingestion_pipeline import DEFAULT_CONFIG, detect_header_row, process_single_file, derive_vehicle_name_from_filename

logger = logging.getLogger("builder_tool")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


@dataclass
class PointCloudEntry:
    vehicle_key: str
    vehicle_name: str
    pointcloud_name: str
    pointcloud_path: str


def normalize_key(text: Optional[str]) -> str:
    if not text:
        return ""
    s = str(text).strip().lower()
    for token in (" ", "_", "-", ".xlsx", ".xls", ".csv"):
        s = s.replace(token, "")
    return s


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(f) or {}
        return json.load(f)


def iter_bom_files(folder: Path) -> list[Path]:
    files = []
    for pattern in ("*.xlsx", "*.xls", "*.csv"):
        files.extend(sorted(folder.glob(pattern)))
    return files


def scan_pointcloud_files(root: Path, extensions: Iterable[str]) -> list[PointCloudEntry]:
    exts = {e.lower() for e in extensions}
    entries: list[PointCloudEntry] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        rel = p.relative_to(root)
        parts = rel.parts
        if len(parts) < 2:
            continue
        vehicle_name = parts[0]
        entries.append(
            PointCloudEntry(
                vehicle_key=normalize_key(vehicle_name),
                vehicle_name=vehicle_name,
                pointcloud_name=p.stem,
                pointcloud_path=str(p.resolve()),
            )
        )
    return entries


def find_part_id_by_vehicle_and_name(duck: DuckDBStore, vehicle_key: str, part_key: str) -> Optional[int]:
    rows = duck.conn.execute(
        """
        SELECT id, source_file, part_name
        FROM parts
        WHERE part_name IS NOT NULL AND source_file IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        rid, source_file, part_name = row
        if normalize_key(source_file) == vehicle_key and normalize_key(part_name) == part_key:
            return int(rid)
    return None


def upsert_pointcloud_only(
    duck: DuckDBStore,
    qdrant: QdrantStore,
    embedder: Optional[BGEEmbedder],
    entry: PointCloudEntry,
) -> int:
    existed = duck.conn.execute(
        """
        SELECT id
        FROM parts
        WHERE source_file=? AND source_row=-1 AND part_name=? AND pointcloud_path=?
        ORDER BY id DESC
        LIMIT 1
        """,
        [entry.vehicle_name, entry.pointcloud_name, entry.pointcloud_path],
    ).fetchone()
    if existed:
        return int(existed[0])

    row = {
        "source_file": entry.vehicle_name,
        "source_row": -1,
        "part_name": entry.pointcloud_name,
        "part_name_source": "pointcloud_name",
        "name_confidence": "direct",
        "part_number": None,
        "vehicle_model": entry.vehicle_name,
        "manufacturer": None,
        "record_type": "pointcloud_only",
        "pointcloud_path": entry.pointcloud_path,
        "level_array": None,
        "material": None,
        "surface_treat": None,
        "process": None,
        "embedding_text": entry.pointcloud_name,
        "raw_data": {"pointcloud_path": entry.pointcloud_path, "vehicle": entry.vehicle_name},
        "form": "pointcloud_only",
    }
    duck.insert_rows([row])
    part_id = int(
        duck.conn.execute(
            """
            SELECT id FROM parts
            WHERE source_file=? AND source_row=-1 AND part_name=? AND pointcloud_path=?
            ORDER BY id DESC LIMIT 1
            """,
            [entry.vehicle_name, entry.pointcloud_name, entry.pointcloud_path],
        ).fetchone()[0]
    )

    if embedder is not None:
        vector = embedder.embed_single(entry.pointcloud_name)
        payload = build_qdrant_payload({**row, "id": part_id})
        qdrant.upsert_vectors([{"id": part_id, "vector": vector, "payload": payload}])
    return part_id


def attach_pointcloud_path_to_part(
    duck: DuckDBStore,
    part_id: int,
    path: str,
):
    current = duck.conn.execute("SELECT pointcloud_path FROM parts WHERE id=?", [part_id]).fetchone()
    existing = current[0] if current else None
    if existing:
        return
    duck.conn.execute("UPDATE parts SET pointcloud_path=?, record_type=COALESCE(record_type,'bom_part') WHERE id=?", [path, part_id])
    duck.conn.commit()


def run_builder(config: dict, progress_cb: Optional[Callable[[str, int, int, str], None]] = None):
    cfg = {**DEFAULT_CONFIG, **config.get("storage", {})}
    builder_cfg = config.get("builder", {})
    input_cfg = config.get("input") or config.get("inputs") or {}
    pc_cfg = config.get("pointcloud", {})
    embedding_cfg = config.get("embedding", {})

    bom_folder = Path(input_cfg.get("bom_folder") or config.get("bom_folder", "data/bom"))
    pointcloud_root = Path(input_cfg.get("pointcloud_root") or config.get("pointcloud_root", "data/pointcloud"))
    if not bom_folder.exists():
        raise ValueError(f"bom_folder 不存在: {bom_folder}")
    if not pointcloud_root.exists():
        raise ValueError(f"pointcloud_root 不存在: {pointcloud_root}")

    fail_report_path = Path(builder_cfg.get("fail_report_path", "output/fail_report.csv"))
    fail_report_path.parent.mkdir(parents=True, exist_ok=True)

    normalizer = ColumnNormalizer(config.get("mapping_path", cfg["mapping_path"]))
    duck = DuckDBStore(cfg["duckdb_path"])
    duck.init_schema()
    qdrant = QdrantStore(cfg["qdrant_path"])

    embedder = None
    if embedding_cfg.get("enabled", True) and embedding_cfg.get("api_key"):
        embedder = BGEEmbedder(
            api_key=embedding_cfg.get("api_key"),
            model=embedding_cfg.get("model", "bge-m3"),
            timeout=int(embedding_cfg.get("timeout_sec", 60)),
            max_retry=int(embedding_cfg.get("retry", 3)),
        )
        qdrant.init_collection(dim=int(cfg.get("vector_dim", 1024)))

    failures = []
    bom_failures = 0
    pointcloud_failures = 0
    summaries = []

    bom_files = iter_bom_files(bom_folder)
    logger.info(f"发现 BOM 文件 {len(bom_files)} 个")
    if progress_cb:
        progress_cb("bom_total", 0, len(bom_files), "")

    run_mode = str(builder_cfg.get("run_mode", "full")).lower()
    existing_sources = set()
    if run_mode == "incremental":
        rows = duck.conn.execute("SELECT DISTINCT source_file FROM parts WHERE source_file IS NOT NULL").fetchall()
        existing_sources = {str(r[0]) for r in rows}

    for idx, fp in enumerate(bom_files, start=1):
        if progress_cb:
            progress_cb("bom_processing", idx, len(bom_files), fp.name)
        try:
            source_name = derive_vehicle_name_from_filename(fp.name)
            if run_mode == "incremental" and source_name in existing_sources:
                logger.info(f"增量模式跳过已存在来源文件: {fp.name}")
                continue
            header_row, header_meta = detect_header_row(
                fp,
                normalizer=normalizer,
                candidate_rows=tuple(builder_cfg.get("header_candidate_rows", [0, 1])),
            )
            min_score = int(builder_cfg.get("min_header_score", 1))
            if header_meta.get("score", -999) < min_score:
                raise ValueError(f"header score too low: {header_meta}")

            summary = process_single_file(
                file_path=fp,
                normalizer=normalizer,
                embedder=embedder,
                duck_store=duck,
                qd_store=qdrant,
                sheet_name=0,
                header_row=header_row,
                drop_unnamed_cols=bool(builder_cfg.get("drop_unnamed_columns", True)),
            )
            summary["status"] = "ok"
            summary["header_row"] = header_row
            summary["header_meta"] = header_meta
            summaries.append(summary)
        except Exception as e:
            failures.append({"file_name": fp.name, "stage": "ingest", "reason": str(e)})
            bom_failures += 1
            logger.error(f"处理失败: {fp.name} -> {e}")

    pc_entries = scan_pointcloud_files(pointcloud_root, pc_cfg.get("extensions", [".stl", ".obj"]))
    logger.info(f"发现点云文件 {len(pc_entries)} 个")
    if progress_cb:
        progress_cb("pointcloud_total", 0, len(pc_entries), "")

    linked = 0
    created_only = 0
    for idx, entry in enumerate(pc_entries, start=1):
        if progress_cb:
            progress_cb("pointcloud_processing", idx, len(pc_entries), entry.pointcloud_name)
        try:
            part_id = find_part_id_by_vehicle_and_name(
                duck,
                vehicle_key=entry.vehicle_key,
                part_key=normalize_key(entry.pointcloud_name),
            )
            if part_id is not None:
                attach_pointcloud_path_to_part(duck, part_id, entry.pointcloud_path)
                linked += 1
            else:
                upsert_pointcloud_only(duck, qdrant, embedder, entry)
                created_only += 1
        except Exception as e:
            failures.append({"file_name": entry.pointcloud_path, "stage": "pointcloud_match", "reason": str(e)})
            pointcloud_failures += 1

    with open(fail_report_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file_name", "stage", "reason"])
        writer.writeheader()
        for item in failures:
            writer.writerow({
                "file_name": item["file_name"],
                "stage": item["stage"],
                "reason": item["reason"],
            })

    summary = {
        "bom_files": len(bom_files),
        "bom_success": len(summaries),
        "bom_failed": bom_failures,
        "pointcloud_files": len(pc_entries),
        "pointcloud_linked": linked,
        "pointcloud_only_created": created_only,
        "pointcloud_failed": pointcloud_failures,
        "total_failed": len(failures),
        "fail_report": str(fail_report_path),
    }
    if progress_cb:
        progress_cb("done", summary.get("bom_success", 0) + summary.get("pointcloud_linked", 0), summary.get("bom_files", 0) + summary.get("pointcloud_files", 0), "")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Builder tool")
    parser.add_argument("--config", required=True, help="yaml/json config path")
    parser.add_argument("--run-mode", default="full", choices=["full", "incremental"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    config.setdefault("builder", {})["run_mode"] = args.run_mode
    if args.dry_run:
        print("dry-run config loaded:")
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return
    run_builder(config)


if __name__ == "__main__":
    main()
