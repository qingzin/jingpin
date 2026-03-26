"""
test_pipeline.py
用 mock 数据验证 pipeline 核心逻辑，无需真实文件和 API。
运行：python3 test/test_pipeline.py
"""
import sys, json
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

import pandas as pd
from core.column_normalizer import ColumnNormalizer
from core.form_detector     import process_structure, structure_summary
from core.embedder          import build_embedding_text, build_qdrant_payload
from core.db_duckdb         import DuckDBStore

MAPPING_PATH = "config/column_mapping.json"

# ════════════════════════════════════════════════════════════════════════════════
# 测试数据：形态 A（Level 列即名称）
# ════════════════════════════════════════════════════════════════════════════════

FORM_A_DATA = {
    "Part Level 0": ["车身系统",  "车身系统",    "车身系统",    "动力系统"],
    "Part Level 1": ["车门总成",  "车门总成",    None,          "电机总成"],
    "Part Level 2": ["前左门",    "前左门",      None,          None],
    "Part Level 3": [None,        "密封条",      None,          None],
    # 合并单元格场景：Part Level 0/1 在第2、3行实际是合并的，pandas 读出来是 NaN
    "Weight (kg)":  ["5.2",       "0.08",        None,          "12.5"],
    "Manufacturer": ["宁波双林",  "宁波双林",    None,          "华域电动"],
    "Materials":    ["钢板",       "EPDM橡胶",   None,          "铝合金"],
    "A2Mac1 部件编号": ["BMW-001","BMW-002",     None,          "BMW-100"],
    "借用车型":       ["BMW X5",  "BMW X5",      "BMW X5",      "BMW X5"],
}

# 形态 A 中，第2行 Part Level 0/1/2 是 None，模拟合并单元格
# ffill 后应该被填充为 车身系统/车门总成/前左门

# ════════════════════════════════════════════════════════════════════════════════
# 测试数据：形态 B（有独立零部件名称列）
# ════════════════════════════════════════════════════════════════════════════════

FORM_B_DATA = {
    "零部件名称":    ["前左门总成",  "前左门铰链上", "前左门铰链下"],
    "Part Level 0":  ["车身系统",    "车身系统",     "车身系统"],
    "Part Level 1":  ["车门总成",    "车门总成",     "车门总成"],
    "Part Level 2":  ["前左门",      "前左门",       "前左门"],
    "Part Level 3":  [None,          "铰链",         "铰链"],
    "重量(kg)":      ["8.5",         "0.35",         "0.35"],
    "制造商":        ["麦格纳",      "麦格纳",       "麦格纳"],
    "材料":          ["钢板",        "不锈钢",       "不锈钢"],
    "车型编号":      ["Tesla M3",    "Tesla M3",     "Tesla M3"],
    "料厚（mm）":    ["1.2",         "2.0",          "2.0"],
    "备注":          [None,          "左上铰链",     "左下铰链"],
}


# ════════════════════════════════════════════════════════════════════════════════
# 测试函数
# ════════════════════════════════════════════════════════════════════════════════

def test_column_normalization():
    print("\n" + "="*60)
    print("TEST 1: 列名归一化")
    print("="*60)

    normalizer = ColumnNormalizer(MAPPING_PATH)

    # 形态 A
    df_a = pd.DataFrame(FORM_A_DATA)
    df_a_norm, meta_a = normalizer.normalize(df_a)

    print(f"\n[形态A] 原始列名: {list(FORM_A_DATA.keys())}")
    print(f"[形态A] 归一化后: {list(df_a_norm.columns)}")
    print(f"[形态A] 层级列:   {meta_a['level_cols']}")
    print(f"[形态A] 未识别列: {meta_a['unmapped']}")

    assert "weight_kg" in df_a_norm.columns,    "weight_kg 归一化失败"
    assert "manufacturer" in df_a_norm.columns, "manufacturer 归一化失败"
    assert "level_0" in df_a_norm.columns,      "Part Level 0 → level_0 失败"
    assert "level_3" in df_a_norm.columns,      "Part Level 3 → level_3 失败"
    assert "part_number" in df_a_norm.columns,  "A2Mac1 部件编号 → part_number 失败"

    # 形态 B
    df_b = pd.DataFrame(FORM_B_DATA)
    df_b_norm, meta_b = normalizer.normalize(df_b)

    print(f"\n[形态B] 归一化后: {list(df_b_norm.columns)}")
    assert "part_name" in df_b_norm.columns,    "零部件名称 → part_name 失败"
    assert "thickness_mm" in df_b_norm.columns, "料厚（mm）→ thickness_mm 失败"
    assert "vehicle_model" in df_b_norm.columns,"车型编号 → vehicle_model 失败"

    print("✅ 列名归一化测试通过")
    return df_a_norm, meta_a, df_b_norm, meta_b


def test_form_detection_and_level_rebuild(df_a_norm, meta_a, df_b_norm, meta_b):
    print("\n" + "="*60)
    print("TEST 2: 形态识别 + 层级重建")
    print("="*60)

    # 形态 A
    df_a_proc = process_structure(df_a_norm, meta_a["level_cols"])
    summary_a = structure_summary(df_a_proc, "test_form_a.xlsx")

    print(f"\n[形态A] 识别结果: form={summary_a['form']}")
    print(f"[形态A] 名称提取: direct={summary_a['name_direct']}, "
          f"derived={summary_a['name_derived']}, missing={summary_a['name_missing']}")

    # 验证前向填充：第2行 (index=2) Part Level 0/1/2 应被填充
    row2 = df_a_proc.iloc[2]
    assert row2["_level_array"] is not None, "第2行层级路径不应为 None（前向填充应生效）"
    assert "车身系统" in row2["_level_array"], f"前向填充失败，level_array={row2['_level_array']}"
    print(f"[形态A] 第2行层级路径（前向填充验证）: {row2['_level_array']}")
    print(f"[形态A] 第1行零件名称: {df_a_proc.iloc[0]['_part_name']} (来源: {df_a_proc.iloc[0]['_name_source']})")
    print(f"[形态A] 第1行层级路径: {df_a_proc.iloc[0]['_level_array']}")
    print(f"[形态A] 第1行（密封条）零件名称: {df_a_proc.iloc[1]['_part_name']}")

    assert summary_a["form"] == "A", f"形态识别错误: {summary_a['form']}"

    # 形态 B
    df_b_proc = process_structure(df_b_norm, meta_b["level_cols"])
    summary_b = structure_summary(df_b_proc, "test_form_b.xlsx")

    print(f"\n[形态B] 识别结果: form={summary_b['form']}")
    print(f"[形态B] 第0行零件名称: {df_b_proc.iloc[0]['_part_name']} (来源: {df_b_proc.iloc[0]['_name_source']})")
    print(f"[形态B] 第0行层级路径: {df_b_proc.iloc[0]['_level_array']}")

    assert summary_b["form"] == "B",                               "形态B识别错误"
    assert df_b_proc.iloc[0]["_part_name"] == "前左门总成",        "形态B名称提取错误"
    assert df_b_proc.iloc[0]["_name_confidence"] == "direct",      "形态B置信度应为direct"
    assert "铰链" in df_b_proc.iloc[1]["_level_array"],            "形态B层级路径应包含铰链节点"

    print("✅ 形态识别 + 层级重建测试通过")
    return df_a_proc, df_b_proc


def test_embedding_text(df_a_proc, df_b_proc):
    print("\n" + "="*60)
    print("TEST 3: Embedding 文本构建")
    print("="*60)

    for df, name in [(df_a_proc, "形态A"), (df_b_proc, "形态B")]:
        for i, (_, row) in enumerate(df.iterrows()):
            text = build_embedding_text(row.to_dict())
            print(f"[{name}] 第{i}行 embedding text: {text}")
            assert text and text != "unknown", f"embedding text 为空: row={i}"
            assert "BMW-001" not in text and "BMW-002" not in text and "BMW-100" not in text, "编号不应进入语义向量文本"
            assert "宁波双林" not in text and "麦格纳" not in text, "供应商不应进入语义向量文本"
            assert "BMW X5" not in text and "Tesla M3" not in text, "车型字段不应进入语义向量文本"
            assert "EPDM橡胶" not in text and "钢板" not in text and "不锈钢" not in text, "材料字段不应进入语义向量文本"

    print("✅ Embedding 文本构建测试通过")


def test_qdrant_payload(df_b_proc):
    print("\n" + "="*60)
    print("TEST 4: Qdrant Payload 构建")
    print("="*60)

    row = df_b_proc.iloc[1].to_dict()
    row.update({
        "source_file": "Tesla_Model3_2022.xlsx",
        "source_row": 1,
        "part_name": row.get("_part_name"),
        "level_array": row.get("_level_array"),
        "level_depth": len(row.get("_level_array") or []),
        "material": "不锈钢",
        "surface_treat": "电泳",
        "weight_kg": "0.35",
        "width_mm": "20",
        "height_mm": "40",
        "length_mm": "80",
    })

    payload = build_qdrant_payload(row)
    print(f"payload: {json.dumps(payload, ensure_ascii=False)}")

    assert payload["vehicle_name"] == "Tesla_Model3_2022.xlsx", "payload 车型名应来自 source_file"
    assert payload["borrowed_vehicle_model"] == "Tesla M3", "原始表格车型字段应单独保留"
    assert payload["part_name"] == "前左门铰链上", "payload 应包含零部件名称"
    assert payload["material"] == "不锈钢", "payload 应包含材料"
    assert payload["surface_treat"] == "电泳", "payload 应包含表面处理"
    assert payload["weight_kg"] == "0.35", "payload 应包含重量"
    assert payload["width_mm"] == "20", "payload 应包含尺寸"
    assert "level_path" in payload and "车门总成" in payload["level_path"], "payload 应包含层级路径"

    print("✅ Qdrant Payload 构建测试通过")


def test_duckdb_write(df_a_proc, df_b_proc):
    print("\n" + "="*60)
    print("TEST 5: DuckDB 写入验证")
    print("="*60)

    import tempfile, os
    normalizer = ColumnNormalizer(MAPPING_PATH)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test.duckdb"
        store   = DuckDBStore(db_path)
        store.init_schema()

        # 构造入库 rows
        rows = []
        for df, fname in [(df_a_proc, "form_a_test.xlsx"), (df_b_proc, "form_b_test.xlsx")]:
            for row_idx, (_, row) in enumerate(df.iterrows()):
                rd = row.to_dict()
                rows.append({
                    "source_file":     fname,
                    "source_row":      row_idx,
                    "part_name":       rd.get("_part_name"),
                    "part_name_source":rd.get("_name_source"),
                    "name_confidence": rd.get("_name_confidence"),
                    "form":            rd.get("_form"),
                    "level_array":     rd.get("_level_array"),
                    "weight_kg":       rd.get("weight_kg"),
                    "manufacturer":    rd.get("manufacturer"),
                    "material":        rd.get("material"),
                    "vehicle_model":   rd.get("vehicle_model"),
                    "embedding_text":  build_embedding_text(rd),
                    "raw_data":        {k: v for k, v in rd.items() if not k.startswith("_")},
                })

        store.insert_rows(rows)

        # 验证写入
        count = store.conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
        print(f"  写入行数: {count}")
        assert count == len(rows), f"行数不匹配: {count} != {len(rows)}"

        # 验证层级查询
        res = store.conn.execute(
            "SELECT part_name, level_array FROM parts WHERE list_contains(level_array, '车门总成')"
        ).df()
        print(f"  list_contains('车门总成') 查询结果: {len(res)} 行")
        print(res[["part_name", "level_array"]].to_string(index=False))
        assert len(res) > 0, "层级查询无结果"

        # 质量报告
        report = store.quality_report()
        print(f"\n  数据质量报告：\n{report.to_string(index=False)}")

        row = store.conn.execute(
            "SELECT part_name, level_array FROM parts WHERE source_file = 'form_a_test.xlsx' ORDER BY source_row DESC LIMIT 1"
        ).fetchone()
        print(f"  最后一行写入结果: {row}")
        assert row[0] == "电机总成", "跨分支前向填充污染，最后一行名称应为电机总成"
        assert row[1] == ["动力系统", "电机总成"], "最后一行层级路径不应继承上一分支的深层节点"

        store.close()

    print("✅ DuckDB 写入测试通过")


# ════════════════════════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    df_a_norm, meta_a, df_b_norm, meta_b = test_column_normalization()
    df_a_proc, df_b_proc                 = test_form_detection_and_level_rebuild(
                                               df_a_norm, meta_a, df_b_norm, meta_b)
    test_embedding_text(df_a_proc, df_b_proc)
    test_qdrant_payload(df_b_proc)
    test_duckdb_write(df_a_proc, df_b_proc)

    print("\n" + "="*60)
    print("🎉 所有测试通过！Pipeline 核心逻辑验证完成")
    print("="*60)
