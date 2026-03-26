"""
db_qdrant.py
Qdrant 本地模式向量存储：建集合、写入、语义检索。
"""
import logging
import warnings
from pathlib import Path
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams,
    PointStruct, Filter, HasIdCondition,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "bom_parts"


class QdrantStore:
    """
    用法：
        store = QdrantStore("db/qdrant_storage")
        store.init_collection(dim=1024)
        store.upsert_vectors(points)  # points: list[dict]
        results = store.search(query_vector, top_k=20, filter_ids=[...])
    """

    def __init__(self, storage_path: str | Path):
        self.storage_path = str(storage_path)
        Path(storage_path).mkdir(parents=True, exist_ok=True)
        self.is_local_mode = True
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Local mode is not recommended for collections with more than 20,000 points.*",
                category=UserWarning,
            )
            self.client = QdrantClient(path=self.storage_path)

    def init_collection(self, dim: int = 1024, recreate: bool = False):
        """
        创建向量集合。
        dim: BGE-M3 输出维度为 1024
        recreate=True 时删除旧集合重建（谨慎使用）
        """
        existing = [c.name for c in self.client.get_collections().collections]

        if COLLECTION_NAME in existing:
            if recreate:
                self.client.delete_collection(COLLECTION_NAME)
                logger.warning(f"已删除旧集合 {COLLECTION_NAME}")
            else:
                logger.info(f"集合 {COLLECTION_NAME} 已存在，跳过创建")
                return

        self.client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info(f"Qdrant 集合 {COLLECTION_NAME} 创建完成，维度={dim}")

    def upsert_vectors(self, points: list[dict], batch_size: int = 200):
        """
        批量写入向量。
        每个 point 结构：
        {
            "id":       <int>,          # DuckDB 行 id（保持两库 id 对齐）
            "vector":   [float, ...],   # embedding 向量
            "payload":  {               # 仅用于结果展示和未来扩展预留
                "vehicle_name":  str,
                "part_name":     str,
                ...
            }
        }
        """
        if not points:
            return

        for i in range(0, len(points), batch_size):
            batch = points[i: i + batch_size]
            structs = [
                PointStruct(
                    id      = p["id"],
                    vector  = p["vector"],
                    payload = p.get("payload", {}),
                )
                for p in batch
            ]
            self.client.upsert(collection_name=COLLECTION_NAME, points=structs)
            logger.debug(f"Qdrant 写入进度: {min(i + batch_size, len(points))}/{len(points)}")

        logger.info(f"Qdrant 写入 {len(points)} 条向量")

    def search(
        self,
        query_vector:    list[float],
        top_k:           int = 20,
        filter_ids:      Optional[list[int]] = None,   # DuckDB 过滤后的 id 白名单
        score_threshold: float = 0.0,
    ) -> list[dict]:
        """
        向量检索。
        filter_ids: 若提供，则只在这些 id 中搜索（混合检索的关键）
        返回: [{"id": int, "score": float, "payload": dict}, ...]
        """
        qdrant_filter = None
        filters = []

        if filter_ids is not None:
            # 用 HasIdCondition 限定候选集
            filters.append(HasIdCondition(has_id=filter_ids))

        if filters:
            qdrant_filter = Filter(must=filters)

        hits = self.client.query_points(
            collection_name = COLLECTION_NAME,
            query           = query_vector,
            limit           = top_k,
            query_filter    = qdrant_filter,
            score_threshold = score_threshold,
        ).points

        return [
            {"id": h.id, "score": h.score, "payload": h.payload}
            for h in hits
        ]

    def count(self) -> int:
        return self.client.get_collection(COLLECTION_NAME).points_count

    def close(self):
        client = getattr(self, "client", None)
        if client is None:
            return
        try:
            client.close()
        except ImportError:
            # Python 解释器关闭阶段，qdrant_client 内部模块可能已被卸载。
            pass
        finally:
            self.client = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
