"""
db_duckdb.py
DuckDB 存储层：建表、写入、查询。
"""
import json
import logging
from pathlib import Path
from typing import Optional
import duckdb
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE SEQUENCE IF NOT EXISTS parts_id_seq START 1;

CREATE TABLE IF NOT EXISTS parts (
    id                  BIGINT DEFAULT nextval('parts_id_seq') PRIMARY KEY,

    -- 来源追踪
    source_file         VARCHAR,
    source_row          INTEGER,

    -- 核心标识
    part_name           VARCHAR,
    part_name_source    VARCHAR,        -- 名称来源列（溯源）
    name_confidence     VARCHAR,        -- 'direct' / 'derived' / 'missing'
    part_number         VARCHAR,
    vehicle_model       VARCHAR,
    manufacturer        VARCHAR,
    record_type         VARCHAR,        -- bom_part / pointcloud_only
    pointcloud_path     VARCHAR,        -- 关联点云文件路径（单值）

    -- 层级结构
    level_array         VARCHAR[],      -- ['车身', '车门', '前左门', '密封条']
    level_depth         INTEGER,        -- 层级深度

    -- 物理属性
    weight_kg           DOUBLE,
    total_weight_kg     DOUBLE,
    quantity            INTEGER,
    width_mm            DOUBLE,
    height_mm           DOUBLE,
    depth_mm            DOUBLE,
    length_mm           DOUBLE,
    thickness_mm        DOUBLE,
    diameter_mm         DOUBLE,

    -- 材料工艺
    material            VARCHAR,
    material_code       VARCHAR,
    material_type       VARCHAR,
    material_grade      VARCHAR,
    surface_treat       VARCHAR,
    process             VARCHAR,

    -- 紧固件
    fastener_weight_kg  DOUBLE,
    fastener_spec       VARCHAR,
    fastener_grade      VARCHAR,
    fastener_color      VARCHAR,

    -- 力矩
    tightening_torque_nm DOUBLE,
    loosening_torque_nm  DOUBLE,
    torque_location      VARCHAR,

    -- 装配
    location            VARCHAR,
    detail              VARCHAR,
    remarks             VARCHAR,
    aux_name            VARCHAR,
    part_type           VARCHAR,
    seq_no              VARCHAR,
    teardown_date       VARCHAR,

    -- A2Mac1
    a2mac1_ref          VARCHAR,

    -- 方位描述（部分表格有独立的左/右/后列）
    left_desc           VARCHAR,
    right_desc          VARCHAR,
    rear_desc           VARCHAR,

    -- 系统/分类
    system              VARCHAR,        -- 所属系统（如 Body、Powertrain）
    nav_node_id         VARCHAR,        -- 目录导航节点ID
    navigation          VARCHAR,        -- 导航/智能网联

    -- 标记
    site                VARCHAR,        -- 场地
    print_flag          VARCHAR,        -- 是否打印
    assembly_teardown   VARCHAR,        -- 总成分拆

    -- 兜底存储（原始行完整数据，零损失）
    raw_data            JSON,

    -- embedding 文本（供调试）
    embedding_text      VARCHAR,

    -- 表格形态
    form                VARCHAR        -- 'A' or 'B'
);

-- 索引：常用过滤字段
CREATE INDEX IF NOT EXISTS idx_parts_vehicle  ON parts(vehicle_model);
CREATE INDEX IF NOT EXISTS idx_parts_mfr      ON parts(manufacturer);
CREATE INDEX IF NOT EXISTS idx_parts_material ON parts(material);
CREATE INDEX IF NOT EXISTS idx_parts_file     ON parts(source_file);
CREATE INDEX IF NOT EXISTS idx_parts_name     ON parts(part_name);
CREATE INDEX IF NOT EXISTS idx_parts_partno   ON parts(part_number);
CREATE INDEX IF NOT EXISTS idx_parts_surface  ON parts(surface_treat);
CREATE INDEX IF NOT EXISTS idx_parts_record_type ON parts(record_type);
"""

# 数值字段列表（入库时转换类型）
NUMERIC_FIELDS = [
    "weight_kg", "total_weight_kg", "width_mm", "height_mm",
    "depth_mm", "length_mm", "thickness_mm", "diameter_mm",
    "fastener_weight_kg", "tightening_torque_nm", "loosening_torque_nm",
]
INT_FIELDS = ["quantity"]


class DuckDBStore:
    """
    用法：
        store = DuckDBStore("db/bom.duckdb")
        store.init_schema()
        store.insert_rows(rows)   # rows: list[dict]
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(self.db_path)

    def init_schema(self):
        self.conn.execute(CREATE_TABLE_SQL)
        self.conn.execute("ALTER TABLE parts ADD COLUMN IF NOT EXISTS record_type VARCHAR")
        self.conn.execute("ALTER TABLE parts ADD COLUMN IF NOT EXISTS pointcloud_path VARCHAR")
        self.conn.commit()
        logger.info(f"DuckDB schema 初始化完成：{self.db_path}")

    def insert_rows(self, rows: list[dict], batch_size: int = 500):
        """批量插入行记录（不含向量，向量存 Qdrant）"""
        if not rows:
            return

        clean_rows = [self._prepare_row(r) for r in rows]

        cols = list(clean_rows[0].keys())
        placeholders = ", ".join(["?" for _ in cols])
        col_names    = ", ".join(cols)
        sql = f"INSERT INTO parts ({col_names}) VALUES ({placeholders})"

        for i in range(0, len(clean_rows), batch_size):
            batch = clean_rows[i: i + batch_size]
            values = [[row[c] for c in cols] for row in batch]
            self.conn.executemany(sql, values)
            self.conn.commit()

        logger.info(f"写入 {len(rows)} 行到 DuckDB")

    def _prepare_row(self, row: dict) -> dict:
        """清洗单行数据，类型转换，raw_data 序列化"""
        out = {}

        # 标量字段直接复制
        scalar_fields = [
            "source_file", "source_row", "part_name", "part_name_source",
            "name_confidence", "part_number", "vehicle_model", "manufacturer",
            "record_type", "pointcloud_path",
            "level_depth", "material", "material_code", "material_type",
            "material_grade", "surface_treat", "process",
            "fastener_spec", "fastener_grade", "fastener_color",
            "torque_location", "location", "detail", "remarks",
            "aux_name", "part_type", "seq_no", "teardown_date",
            "a2mac1_ref", "left_desc", "right_desc", "rear_desc",
            "system", "nav_node_id", "navigation",
            "site", "print_flag", "assembly_teardown",
            "embedding_text", "form",
        ]
        for f in scalar_fields:
            val = row.get(f)
            out[f] = _clean_str(val)

        # 数值字段
        for f in NUMERIC_FIELDS:
            out[f] = _to_float(row.get(f))
        for f in INT_FIELDS:
            out[f] = _to_int(row.get(f))

        # level_array（DuckDB VARCHAR[]）
        la = row.get("level_array") or row.get("_level_array")
        out["level_array"] = la if isinstance(la, list) and la else None
        out["level_depth"] = len(la) if isinstance(la, list) else 0

        # raw_data → JSON 字符串
        raw = row.get("raw_data", {})
        out["raw_data"] = json.dumps(raw, ensure_ascii=False, default=str)

        return out

    def quality_report(self) -> pd.DataFrame:
        """数据质量统计报告"""
        sql = """
        SELECT
            source_file,
            form,
            COUNT(*)                                           AS total_rows,
            ROUND(COUNT(part_name) * 100.0 / COUNT(*), 1)     AS name_coverage_pct,
            ROUND(COUNT(level_array) * 100.0 / COUNT(*), 1)   AS level_coverage_pct,
            ROUND(COUNT(weight_kg) * 100.0 / COUNT(*), 1)     AS weight_coverage_pct,
            ROUND(COUNT(material) * 100.0 / COUNT(*), 1)      AS material_coverage_pct,
            ROUND(COUNT(material_type) * 100.0 / COUNT(*), 1) AS material_type_pct,
            ROUND(COUNT(material_grade) * 100.0 / COUNT(*), 1) AS material_grade_pct,
            COUNT_IF(name_confidence = 'missing')              AS name_missing_cnt,
            COUNT_IF(name_confidence = 'derived')              AS name_derived_cnt
        FROM parts
        GROUP BY source_file, form
        ORDER BY name_coverage_pct ASC
        """
        return self.conn.execute(sql).df()

    def search_by_filter(
        self,
        source_file:    Optional[str] = None,
        vehicle_model:  Optional[str] = None,
        part_name_like: Optional[str] = None,
        part_number:    Optional[str] = None,
        manufacturer:   Optional[str] = None,
        material_like:  Optional[str] = None,
        surface_treat:  Optional[str] = None,
        process_like:   Optional[str] = None,
        weight_min:     Optional[float] = None,
        weight_max:     Optional[float] = None,
        length_min:     Optional[float] = None,
        length_max:     Optional[float] = None,
        width_min:      Optional[float] = None,
        width_max:      Optional[float] = None,
        height_min:     Optional[float] = None,
        height_max:     Optional[float] = None,
        thickness_min:  Optional[float] = None,
        thickness_max:  Optional[float] = None,
        level_contains: Optional[str] = None,   # 层级包含某个节点
        level_index:    Optional[int] = None,    # 指定层级位置（0-based）
        level_value:    Optional[str] = None,    # 该位置的值
        limit: int = 100,
    ) -> pd.DataFrame:
        """结构化过滤查询，返回候选集（供混合检索使用）"""
        conditions = []
        params     = []

        if source_file:
            conditions.append("source_file ILIKE ?")
            params.append(f"%{source_file}%")

        if vehicle_model:
            conditions.append("vehicle_model ILIKE ?")
            params.append(f"%{vehicle_model}%")

        if part_name_like:
            conditions.append("part_name ILIKE ?")
            params.append(f"%{part_name_like}%")

        if part_number:
            conditions.append("part_number = ?")
            params.append(part_number)

        if manufacturer:
            conditions.append("manufacturer ILIKE ?")
            params.append(f"%{manufacturer}%")

        if material_like:
            conditions.append("material ILIKE ?")
            params.append(f"%{material_like}%")

        if surface_treat:
            conditions.append("surface_treat ILIKE ?")
            params.append(f"%{surface_treat}%")

        if process_like:
            conditions.append("process ILIKE ?")
            params.append(f"%{process_like}%")

        if weight_min is not None:
            conditions.append("weight_kg >= ?")
            params.append(weight_min)

        if weight_max is not None:
            conditions.append("weight_kg <= ?")
            params.append(weight_max)

        if length_min is not None:
            conditions.append("length_mm >= ?")
            params.append(length_min)

        if length_max is not None:
            conditions.append("length_mm <= ?")
            params.append(length_max)

        if width_min is not None:
            conditions.append("width_mm >= ?")
            params.append(width_min)

        if width_max is not None:
            conditions.append("width_mm <= ?")
            params.append(width_max)

        if height_min is not None:
            conditions.append("height_mm >= ?")
            params.append(height_min)

        if height_max is not None:
            conditions.append("height_mm <= ?")
            params.append(height_max)

        if thickness_min is not None:
            conditions.append("thickness_mm >= ?")
            params.append(thickness_min)

        if thickness_max is not None:
            conditions.append("thickness_mm <= ?")
            params.append(thickness_max)

        if level_contains:
            conditions.append("list_contains(level_array, ?)")
            params.append(level_contains)

        if level_index is not None and level_value:
            # DuckDB 数组下标 1-based
            conditions.append(f"level_array[{level_index + 1}] = ?")
            params.append(level_value)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql   = f"SELECT * FROM parts {where} LIMIT {limit}"

        return self.conn.execute(sql, params).df()

    def get_rows_by_ids(self, ids: list[int]) -> pd.DataFrame:
        """按 id 批量取回完整记录，并保持传入顺序。"""
        if not ids:
            return pd.DataFrame()

        placeholders = ", ".join(["?" for _ in ids])
        df = self.conn.execute(
            f"SELECT * FROM parts WHERE id IN ({placeholders})",
            ids,
        ).df()
        order = {rid: idx for idx, rid in enumerate(ids)}
        return df.sort_values(by="id", key=lambda s: s.map(order)).reset_index(drop=True)

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _clean_str(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, float) and np.isnan(val):
        return None
    s = str(val).strip()
    return s if s else None


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        if isinstance(val, float) and np.isnan(val):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val) -> Optional[int]:
    f = _to_float(val)
    return int(f) if f is not None else None
