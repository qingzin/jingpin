"""
search_presenter.py
搜索结果整理成 CLI / Web 都可复用的展示数据。
"""
from __future__ import annotations

from typing import Iterable


FIXED_COLUMNS = ["rank", "score", "source_file", "part_name", "level_path"]
FILTER_TO_COLUMN = {
    "vehicle_name": "source_file",
    "source_file": "source_file",
    "borrowed_vehicle_model": "vehicle_model",
    "part_number": "part_number",
    "manufacturer": "manufacturer",
    "material": "material",
    "material_type": "material_type",
    "material_grade": "material_grade",
    "surface_treat": "surface_treat",
    "process": "process",
    "system": "system",
    "weight_kg": "weight_kg",
    "total_weight_kg": "total_weight_kg",
    "length_mm": "length_mm",
    "width_mm": "width_mm",
    "height_mm": "height_mm",
    "depth_mm": "depth_mm",
    "thickness_mm": "thickness_mm",
    "diameter_mm": "diameter_mm",
    "quantity": "quantity",
    "level_depth": "level_depth",
    "level_contains": "level_path",
}
EXCLUDED_ROW_COLUMNS = {"level_array", "raw_data", "embedding_text"}
COLUMN_LABELS = {
    "rank": "排名",
    "score": "分数",
    "id": "ID",
    "source_file": "车型",
    "source_row": "源行号",
    "part_name": "零部件名称",
    "level_path": "层级路径",
    "part_name_source": "名称来源列",
    "name_confidence": "名称置信度",
    "vehicle_model": "借用车型",
    "part_number": "零件编号",
    "manufacturer": "制造商",
    "material": "材料",
    "material_type": "材料类型",
    "material_grade": "材料牌号",
    "surface_treat": "表面处理",
    "process": "工艺",
    "system": "系统",
    "weight_kg": "重量(kg)",
    "total_weight_kg": "总重量(kg)",
    "length_mm": "长度(mm)",
    "width_mm": "宽度(mm)",
    "height_mm": "高度(mm)",
    "depth_mm": "深度(mm)",
    "thickness_mm": "厚度(mm)",
    "diameter_mm": "直径(mm)",
    "quantity": "数量",
    "level_depth": "层级深度",
    "form": "表格形态",
    "material_code": "材料编码",
    "fastener_weight_kg": "紧固件重量(kg)",
    "fastener_spec": "紧固件规格",
    "fastener_grade": "紧固件等级",
    "fastener_color": "紧固件颜色",
    "tightening_torque_nm": "拧紧扭矩(Nm)",
    "loosening_torque_nm": "拧松扭矩(Nm)",
    "torque_location": "扭矩位置",
    "location": "位置",
    "detail": "细节",
    "remarks": "备注",
    "aux_name": "辅助名称",
    "part_type": "零件类型",
    "seq_no": "序号",
    "teardown_date": "拆解日期",
    "a2mac1_ref": "A2Mac1参考",
    "left_desc": "左描述",
    "right_desc": "右描述",
    "rear_desc": "后描述",
    "nav_node_id": "导航节点ID",
    "navigation": "导航",
    "site": "场地",
    "print_flag": "打印标记",
    "assembly_teardown": "总成分拆",
}


def normalize_level_array(val) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, tuple):
        return [str(v) for v in val]
    if hasattr(val, "tolist"):
        converted = val.tolist()
        if isinstance(converted, list):
            return [str(v) for v in converted]
    return []


def vehicle_summary(results: list[dict]) -> list[dict]:
    agg = {}
    for item in results:
        row = item["row"]
        vehicle = row.get("source_file") or "unknown"
        score = item["score"] if item["score"] is not None else 0.0
        summary = agg.setdefault(vehicle, {
            "vehicle": vehicle,
            "matched_parts": 0,
            "best_score": score,
            "example_part": row.get("part_name"),
        })
        summary["matched_parts"] += 1
        if score >= summary["best_score"]:
            summary["best_score"] = score
            summary["example_part"] = row.get("part_name")
    return sorted(agg.values(), key=lambda x: (x["best_score"], x["matched_parts"]), reverse=True)


def infer_display_columns(results: list[dict], filters: Iterable) -> list[str]:
    columns = list(FIXED_COLUMNS)
    for filter_obj in filters:
        column = FILTER_TO_COLUMN.get(filter_obj.field)
        if column and column not in columns:
            columns.append(column)

    remaining_columns = []
    for item in results:
        row = item.get("row", {})
        for column in row.keys():
            if column in EXCLUDED_ROW_COLUMNS or column in columns:
                continue
            remaining_columns.append(column)

    for column in remaining_columns:
        if column not in columns:
            columns.append(column)
    return columns


def present_results(results: list[dict], filters: Iterable) -> dict:
    columns = infer_display_columns(results, filters)
    rows = []
    for item in results:
        row = item["row"]
        level_path = " > ".join(normalize_level_array(row.get("level_array")))
        display_row = {
            "rank": item["rank"],
            "score": item["score"],
            "source_file": row.get("source_file"),
            "part_name": row.get("part_name"),
            "level_path": level_path,
        }
        for column in columns:
            if column in display_row:
                continue
            display_row[column] = row.get(column)
        rows.append(display_row)
    return {
        "columns": [{"key": key, "label": COLUMN_LABELS.get(key, key)} for key in columns],
        "rows": rows,
        "vehicle_summary": vehicle_summary(results),
    }
