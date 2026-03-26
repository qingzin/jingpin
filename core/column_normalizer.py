"""
column_normalizer.py
将原始 Excel/CSV 列名映射到统一的英文字段名
"""
import json
import re
from pathlib import Path


# ── 加载映射表 ────────────────────────────────────────────────────────────────

def load_mapping(mapping_path: str | Path) -> dict[str, str]:
    """
    返回 {原始列名 (小写去空格): 标准英文字段名} 的查找字典。
    对 BOM 层级列（Part Level 0-8 / 层级1-3）单独处理，保留原始列名。
    """
    with open(mapping_path, encoding="utf-8") as f:
        groups = json.load(f)["groups"]

    lookup: dict[str, str] = {}
    for group in groups:
        std_en = group["standard_name_en"]
        # BOM 层级列不归并到同一字段，保留各自原始列名
        if std_en == "bom_level":
            continue
        for variant in group["variants"]:
            key = _normalize_key(variant)
            lookup[key] = std_en
    return lookup


def _normalize_key(col: str) -> str:
    """列名标准化 key：去除首尾空格、统一小写、压缩空白字符（含换行符）"""
    col = col.strip()
    # Excel 单元格换行符统一转为空格
    col = col.replace("\n", " ").replace("\r", " ")
    col = col.lower()
    col = re.sub(r"\s+", " ", col)   # 压缩连续空白
    col = col.strip()
    # 去掉首位的 * 号（如 *零部件名称）
    col = col.lstrip("*").strip()
    return col


# ── Level 列检测 ──────────────────────────────────────────────────────────────

# 英文 Part Level 0-8
_PART_LEVEL_PATTERN = re.compile(r"^part\s+level\s+(\d+)$", re.IGNORECASE)
# 中文层级1-9
_ZH_LEVEL_PATTERN   = re.compile(r"^层级\s*(\d+)$")


def detect_level_col(col: str) -> int | None:
    """
    判断列名是否为层级列，返回层级序号（0-based）；非层级列返回 None。
    英文 Part Level N → 序号 N
    中文 层级N       → 序号 N-1（层级1 = 第0层）
    """
    # 统一处理换行符和多余空格
    key = col.strip().replace("\n", " ").replace("\r", " ")
    key = re.sub(r"\s+", " ", key).strip()
    m = _PART_LEVEL_PATTERN.match(key)
    if m:
        return int(m.group(1))
    m = _ZH_LEVEL_PATTERN.match(key)
    if m:
        return int(m.group(1)) - 1   # 层级1 → index 0
    return None


# ── 主接口 ────────────────────────────────────────────────────────────────────

class ColumnNormalizer:
    """
    用法：
        normalizer = ColumnNormalizer("config/column_mapping.json")
        renamed_df, meta = normalizer.normalize(df)
    """

    # 标准名称集合，用于形态 B 判断
    PART_NAME_STD = "part_name"

    def __init__(self, mapping_path: str | Path):
        self.lookup = load_mapping(mapping_path)

    def normalize(self, df):
        """
        对 DataFrame 进行列名归一化。

        返回：
          - renamed_df  : 列名已归一化的 DataFrame
          - meta        : {
                "level_cols": [(原始列名, 序号), ...],   # 按序号排序
                "unmapped":   [未能识别的原始列名, ...]
            }
        """
        import pandas as pd

        rename_map: dict[str, str] = {}
        level_cols: list[tuple[str, int]] = []
        unmapped:   list[str] = []

        for col in df.columns:
            # 1. 检查是否是层级列
            level_idx = detect_level_col(col)
            if level_idx is not None:
                # 层级列重命名为 level_0, level_1, ...
                new_name = f"level_{level_idx}"
                rename_map[col] = new_name
                level_cols.append((new_name, level_idx))
                continue

            # 2. 查 lookup 表
            key = _normalize_key(col)
            if key in self.lookup:
                std = self.lookup[key]
                # 同一标准字段出现多次时，保留第一个，后续加 _dup 后缀避免覆盖
                target = std
                count = 0
                while target in rename_map.values():
                    count += 1
                    target = f"{std}_dup{count}"
                rename_map[col] = target
            else:
                unmapped.append(col)

        # 执行重命名（未识别的列保留原名）
        renamed_df = df.rename(columns=rename_map)

        # 按序号排序 level_cols
        level_cols_sorted = sorted(level_cols, key=lambda x: x[1])

        return renamed_df, {
            "level_cols": level_cols_sorted,   # [(level_0, 0), (level_1, 1), ...]
            "unmapped":   unmapped,
        }
