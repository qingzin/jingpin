"""
form_detector.py
识别表格形态（A / B），提取零件名称，重建层级路径。
"""
import pandas as pd
import numpy as np
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# 形态判断
# ─────────────────────────────────────────────────────────────────────────────

def detect_form(df: pd.DataFrame, level_col_names: list[str]) -> str:
    """
    判断表格形态：
      形态 B：表头中存在零件名称列（归一化前后均检查，不依赖 JSON 配置）
      形态 A：否则（Level 列即名称）

    返回 'A' 或 'B'
    """
    # 归一化后可能的标准字段名
    PART_NAME_NORMALIZED = {"part_name", "partname"}

    # 原始列名中只要包含这些关键词，就认为是名称列
    PART_NAME_KEYWORDS = [
        "零部件名称", "零件名称", "部件名称",
        "part name", "partname", "component name", "item name",
    ]

    col_set_lower = {str(c).strip().lower() for c in df.columns}

    # 1. 检查归一化后的标准字段名（精确匹配）
    for name in PART_NAME_NORMALIZED:
        if name in col_set_lower:
            return "B"

    # 2. 检查原始列名是否包含关键词（模糊匹配，应对 JSON 配置差异）
    for col in df.columns:
        col_lower = str(col).strip().lower()
        for kw in PART_NAME_KEYWORDS:
            if kw in col_lower:
                return "B"

    return "A"


# ─────────────────────────────────────────────────────────────────────────────
# 合并单元格空值修复
# ─────────────────────────────────────────────────────────────────────────────

def fix_merged_cells(df: pd.DataFrame, level_col_names: list[str]) -> pd.DataFrame:
    """
    Excel 合并单元格展开后，层级列会出现大量 NaN。
    这里不能直接对整列做 ffill，否则上一分支的深层节点会串到下一分支。

    规则：
      1. 仅在当前行没有显式切换上层节点时，才沿用上一行同层值
      2. 一旦当前行某个上层节点发生变化，更深层空值必须保持为空
    """
    cols_to_fill = [c for c in level_col_names if c in df.columns]
    if not cols_to_fill:
        return df

    df = df.copy()
    prev_values = [None] * len(cols_to_fill)

    for row_idx in df.index:
        current_values = [None] * len(cols_to_fill)
        ancestor_changed = False

        for level_idx, col in enumerate(cols_to_fill):
            raw_val = _clean_cell(df.at[row_idx, col])
            if raw_val is not None:
                current_values[level_idx] = raw_val
                if raw_val != prev_values[level_idx]:
                    ancestor_changed = True
            elif not ancestor_changed:
                current_values[level_idx] = prev_values[level_idx]

            df.at[row_idx, col] = current_values[level_idx]

        prev_values = current_values

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 层级路径重建
# ─────────────────────────────────────────────────────────────────────────────

def _clean_cell(val) -> Optional[str]:
    """清洗单元格值：NaN / 空字符串 / 纯空格 → None"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip()
    return s if s else None


def build_level_path(row: pd.Series, level_col_names: list[str]) -> list[str]:
    """
    按列序号顺序，收集非空的层级值，组成层级路径数组。
    示例：['车身系统', '车门总成', '前左门', '密封条']
    """
    path = []
    for col in level_col_names:
        val = _clean_cell(row.get(col))
        if val:
            path.append(val)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 零件名称提取
# ─────────────────────────────────────────────────────────────────────────────

def extract_part_name_form_a(
    row: pd.Series,
    level_col_names: list[str],
) -> tuple[Optional[str], Optional[str]]:
    """
    形态 A：从层级列中取最深非空值作为零件名称。
    返回 (零件名称, 来源列名)
    """
    # 从最深层级往上找
    for col in reversed(level_col_names):
        val = _clean_cell(row.get(col))
        if val:
            return val, col
    return None, None


def extract_part_name_form_b(
    row: pd.Series,
) -> tuple[Optional[str], str]:
    """
    形态 B：查找名称列，兼容不同 JSON 配置下的归一化结果。
    返回 (零件名称, 来源列名)
    """
    # 可能的列名（归一化后 or 原始列名都可能存在）
    CANDIDATES = [
        "part_name", "零部件名称", "零件名称", "部件名称",
        "partname", "component name", "item name",
    ]
    for col in CANDIDATES:
        val = _clean_cell(row.get(col))
        if val:
            return val, col

    # 兜底：遍历所有列，找包含"名称"关键词的列
    for col in row.index:
        col_lower = str(col).strip().lower()
        if "名称" in col_lower or "name" in col_lower:
            # 排除层级列
            if col_lower.startswith("level_"):
                continue
            val = _clean_cell(row.get(col))
            if val:
                return val, col

    return None, "part_name"


# ─────────────────────────────────────────────────────────────────────────────
# 主处理函数：对整张表应用
# ─────────────────────────────────────────────────────────────────────────────

def process_structure(
    df: pd.DataFrame,
    level_cols_meta: list[tuple[str, int]],   # [(level_0, 0), (level_1, 1), ...]
) -> pd.DataFrame:
    """
    1. 前向填充修复合并单元格
    2. 判断形态
    3. 提取零件名称 + 重建层级路径
    4. 新增三列：_part_name, _level_array, _name_source, _name_confidence
    """
    level_col_names = [col for col, _ in level_cols_meta]   # 按序已排好

    # Step 1: 修复合并单元格
    df = fix_merged_cells(df, level_col_names)

    # Step 2: 判断形态
    form = detect_form(df, level_col_names)

    # Step 3: 逐行提取名称 + 层级路径
    names        = []
    name_sources = []
    confidences  = []
    level_arrays = []

    for _, row in df.iterrows():
        # 层级路径（两种形态都需要）
        path = build_level_path(row, level_col_names)
        level_arrays.append(path if path else None)

        # 零件名称
        if form == "B":
            name, src = extract_part_name_form_b(row)
        else:
            name, src = extract_part_name_form_a(row, level_col_names)

        names.append(name)
        name_sources.append(src)

        # 置信度标记
        if name is None:
            confidences.append("missing")
        elif form == "B":
            confidences.append("direct")
        else:
            confidences.append("derived")

    df = df.copy()
    df["_part_name"]        = names
    df["_level_array"]      = level_arrays
    df["_name_source"]      = name_sources
    df["_name_confidence"]  = confidences
    df["_form"]             = form

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 快速统计
# ─────────────────────────────────────────────────────────────────────────────

def structure_summary(df: pd.DataFrame, source_file: str = "") -> dict:
    total = len(df)
    form  = df["_form"].iloc[0] if "_form" in df.columns and total > 0 else "unknown"

    return {
        "source_file":        source_file,
        "form":               form,
        "total_rows":         total,
        "name_direct":        int((df["_name_confidence"] == "direct").sum()),
        "name_derived":       int((df["_name_confidence"] == "derived").sum()),
        "name_missing":       int((df["_name_confidence"] == "missing").sum()),
        "level_array_filled": int(df["_level_array"].notna().sum()),
        "level_array_null":   int(df["_level_array"].isna().sum()),
    }
