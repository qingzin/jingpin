"""
embed_only.py
从现有 DuckDB 读取 embedding_text，调用 BGE-M3 API 生成向量，写入 Qdrant。
支持断点续传：已写入 Qdrant 的 id 自动跳过。

用法：
    python embed_only.py --api-key "your_token"
    python embed_only.py --api-key "your_token" --batch 64   # 调大批次
    python embed_only.py --api-key "your_token" --resume     # 断点续传（默认开启）
"""

import argparse
import logging
import os
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

from core.embedder import BGEEmbedder, build_qdrant_payload
from core.db_qdrant import QdrantStore

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(message)s",
    datefmt = "%H:%M:%S",
)
logger = logging.getLogger(__name__)

VECTOR_DIM      = 1024
COLLECTION_NAME = "bom_parts"


# ─────────────────────────────────────────────────────────────────────────────
# 获取已写入 Qdrant 的 id 集合
# ─────────────────────────────────────────────────────────────────────────────

def get_existing_qdrant_ids(qd_store: QdrantStore) -> set[int]:
    """
    滚动读取 Qdrant 中已有的所有点 id，用于断点续传。
    """
    from qdrant_client.models import ScrollRequest
    existing = set()
    offset   = None

    logger.info("读取 Qdrant 已有向量 id...")
    while True:
        result = qd_store.client.scroll(
            collection_name = COLLECTION_NAME,
            limit           = 1000,
            offset          = offset,
            with_vectors    = False,
            with_payload    = False,
        )
        points, next_offset = result
        for p in points:
            existing.add(p.id)
        if next_offset is None:
            break
        offset = next_offset

    logger.info(f"Qdrant 中已有 {len(existing)} 条向量")
    return existing


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def run_embed_only(
    api_key:    str,
    duckdb_path: str = "db/bom.duckdb",
    qdrant_path: str = "db/qdrant_storage",
    batch_size: int  = 32,
    resume:     bool = True,
):
    # ── 初始化组件 ─────────────────────────────────────────────────────────────
    embedder = BGEEmbedder(api_key=api_key, batch_size=batch_size)
    logger.info(f"Embedder 初始化完成，batch_size={batch_size}")

    qd_store = QdrantStore(qdrant_path)
    qd_store.init_collection(dim=VECTOR_DIM)

    conn = duckdb.connect(duckdb_path, read_only=True)

    # ── 读取 DuckDB 总量 ───────────────────────────────────────────────────────
    total = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    logger.info(f"DuckDB 共 {total} 行")

    # ── 断点续传：找出尚未写入的 id ────────────────────────────────────────────
    if resume:
        existing_ids = get_existing_qdrant_ids(qd_store)
    else:
        existing_ids = set()
        logger.info("resume=False，全量重新写入")

    # 从 DuckDB 查出所有待处理的行
    cursor = conn.execute("""
        SELECT
            id, embedding_text, source_file, source_row, part_name, part_number,
            level_array, level_depth, form,
            vehicle_model, manufacturer,
            material, material_code, material_type, material_grade,
            surface_treat, process,
            weight_kg, total_weight_kg, quantity,
            width_mm, height_mm, depth_mm, length_mm, thickness_mm, diameter_mm,
            location, detail, remarks, aux_name, part_type,
            system, assembly_teardown, site
        FROM parts
        ORDER BY id
    """)
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()

    # 过滤掉已有的
    pending = [r for r in rows if r["id"] not in existing_ids]
    skip_count = len(rows) - len(pending)

    logger.info(f"待写入：{len(pending)} 条，跳过（已有）：{skip_count} 条")

    if not pending:
        logger.info("✅ 所有向量已写入，无需重跑")
        return

    # ── 分批处理 ───────────────────────────────────────────────────────────────
    t0           = time.time()
    success      = 0
    error_ids    = []

    with tqdm(total=len(pending), desc="生成 embedding", unit="行") as pbar:
        for i in range(0, len(pending), batch_size):
            batch = pending[i: i + batch_size]
            ids   = [r["id"] for r in batch]
            texts = [r["embedding_text"] or "unknown" for r in batch]

            try:
                vectors = embedder.embed(texts)
            except Exception as e:
                logger.error(f"  Embedding 失败（id {ids[0]}~{ids[-1]}）: {e}")
                error_ids.extend(ids)
                pbar.update(len(batch))
                continue

            # 构造 Qdrant points
            points = []
            for row, vec in zip(batch, vectors):
                points.append({
                    "id":     int(row["id"]),
                    "vector": vec,
                    "payload": build_qdrant_payload(row),
                })

            try:
                qd_store.upsert_vectors(points)
                success += len(batch)
            except Exception as e:
                logger.error(f"  Qdrant 写入失败（id {ids[0]}~{ids[-1]}）: {e}")
                error_ids.extend(ids)

            pbar.update(len(batch))

            # 每1000条打一次进度日志（方便长时间运行监控）
            if (i // batch_size) % (1000 // batch_size) == 0 and i > 0:
                elapsed  = time.time() - t0
                speed    = success / elapsed
                eta      = (len(pending) - i) / speed if speed > 0 else 0
                logger.info(
                    f"  进度 {i}/{len(pending)} | "
                    f"速度 {speed:.1f}行/s | "
                    f"预计剩余 {eta/60:.1f} 分钟"
                )

    # ── 完成报告 ───────────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    total_in_qdrant = qd_store.count()

    print(f"""
{'='*60}
✅ Embedding 完成！

  本次写入：  {success} 条
  本次跳过：  {skip_count} 条（已有）
  本次失败：  {len(error_ids)} 条
  Qdrant 总量：{total_in_qdrant} 条
  耗时：      {elapsed/60:.1f} 分钟
{'='*60}
""")

    if error_ids:
        logger.warning(f"失败的 id（可重跑恢复）: {error_ids[:20]}{'...' if len(error_ids)>20 else ''}")
        logger.warning("重新运行同一命令即可自动续跑失败的部分（断点续传）")


# ─────────────────────────────────────────────────────────────────────────────
# 命令行入口
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BOM Embedding 写入（断点续传）")
    parser.add_argument("--api-key",  default=None,              help="BGE API Bearer Token")
    parser.add_argument("--db",       default="db/bom.duckdb",   help="DuckDB 路径")
    parser.add_argument("--qdrant",   default="db/qdrant_storage", help="Qdrant 存储目录")
    parser.add_argument("--batch",    type=int, default=32,       help="每批 embedding 条数（默认32）")
    parser.add_argument("--no-resume",action="store_true",        help="忽略已有向量，全量重写")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("BGE_API_KEY")
    if not api_key:
        print("❌ 未提供 API Key，请用 --api-key 或环境变量 BGE_API_KEY 提供")
        exit(1)

    run_embed_only(
        api_key     = api_key,
        duckdb_path = args.db,
        qdrant_path = args.qdrant,
        batch_size  = args.batch,
        resume      = not args.no_resume,
    )
