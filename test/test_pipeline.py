import io
import json
from pathlib import Path

import pandas as pd

from core.column_normalizer import ColumnNormalizer
from ingestion_pipeline import detect_header_row, read_file


MAPPING_PATH = "config/column_mapping.json"


def test_detect_header_prefers_second_row_when_first_row_is_mostly_unnamed(tmp_path):
    file_path = tmp_path / "bom_header_shift.csv"
    # 第1行为脏头（大量空值），第2行是真正表头
    csv_text = ",,,\n零部件名称,Part Level 0,Part Level 1,重量(kg)\n前门铰链上,车身系统,车门总成,0.35\n"
    file_path.write_text(csv_text, encoding="utf-8")

    normalizer = ColumnNormalizer(MAPPING_PATH)
    header_row, meta = detect_header_row(file_path, normalizer=normalizer)

    assert header_row == 1, f"expected header row 1, got {header_row}, meta={meta}"
    assert meta["unnamed_ratio"] < 0.5


def test_read_file_drops_unnamed_columns(tmp_path):
    file_path = tmp_path / "bom_drop_unnamed.csv"
    csv_text = "零部件名称,,Part Level 0\n前门铰链上,ignored,车身系统\n"
    file_path.write_text(csv_text, encoding="utf-8")

    df = read_file(file_path, header_row=0, drop_unnamed_cols=True)
    assert "_unnamed_1" not in df.columns
    assert list(df.columns) == ["零部件名称", "Part Level 0"]
    assert df.iloc[0]["零部件名称"] == "前门铰链上"
