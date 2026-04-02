from __future__ import annotations

import shutil
from pathlib import Path

from qt_bootstrap import configure_qt_runtime

configure_qt_runtime()

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
    QSplitter,
)

from core.db_duckdb import DuckDBStore
from core.db_qdrant import QdrantStore
from core.embedder import BGEEmbedder
from core.query_parser import infer_target_component
from core.search_engine import QueryFilter, SearchEngine, SearchQuery
from core.search_presenter import present_results


class SearchWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("零部件检索（PySide6）")
        self.resize(1280, 780)
        self.engine: SearchEngine | None = None
        self.last_rows: list[dict] = []

        root = QWidget()
        self.setCentralWidget(root)
        page = QVBoxLayout(root)

        splitter = QSplitter(Qt.Horizontal)
        page.addWidget(splitter)
        left_panel = QWidget()
        right_panel = QWidget()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([980, 300])
        v = QVBoxLayout(left_panel)

        top = QWidget()
        form = QFormLayout(top)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.model = QLineEdit("bge-m3")
        self.db = QLineEdit(str(Path("db/bom.duckdb").resolve()))
        self.qdrant = QLineEdit(str(Path("db/qdrant_storage").resolve()))

        form.addRow("API Key", self.api_key)
        form.addRow("Embedding模型", self.model)
        form.addRow("DuckDB", self.db)
        form.addRow("Qdrant目录", self.qdrant)

        conn_btn = QPushButton("初始化检索")
        conn_btn.clicked.connect(self.init_runtime)
        form.addRow(conn_btn)
        v.addWidget(top)

        query_row = QWidget()
        qh = QHBoxLayout(query_row)
        self.query = QLineEdit("发动机总成")
        self.topk = QSpinBox()
        self.topk.setRange(1, 1000)
        self.topk.setValue(20)
        self.field = QComboBox()
        self.field.setMinimumWidth(260)
        self.op = QComboBox()
        self.op.addItems(["=", "~", ">", ">=", "<", "<="])
        self.op.setToolTip("~ 表示模糊匹配（等价于包含/LIKE）")
        self.value = QLineEdit()
        add_filter_btn = QPushButton("添加筛选")
        add_filter_btn.clicked.connect(self.add_filter)
        remove_filter_btn = QPushButton("删除选中筛选")
        remove_filter_btn.clicked.connect(self.remove_selected_filter)
        clear_filter_btn = QPushButton("清空筛选")
        clear_filter_btn.clicked.connect(self.clear_filters)
        self.search_btn = QPushButton("检索")
        self.search_btn.clicked.connect(self.search)
        self.search_btn.setEnabled(False)

        qh.addWidget(QLabel("查询"))
        qh.addWidget(self.query, 3)
        qh.addWidget(QLabel("top_k"))
        qh.addWidget(self.topk)
        qh.addWidget(self.field)
        qh.addWidget(self.op)
        qh.addWidget(self.value, 2)
        qh.addWidget(add_filter_btn)
        qh.addWidget(remove_filter_btn)
        qh.addWidget(clear_filter_btn)
        qh.addWidget(self.search_btn)
        v.addWidget(query_row)
        v.addWidget(QLabel("筛选操作符说明：`~` 表示模糊匹配（包含关系），例如 part_name ~ 铰链。"))

        self.filter_table = QTableWidget(0, 3)
        self.filter_table.setHorizontalHeaderLabels(["字段", "操作符", "值"])
        v.addWidget(self.filter_table, 1)

        self.result_table = QTableWidget(0, 0)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        v.addWidget(self.result_table, 4)

        actions = QWidget()
        ah = QHBoxLayout(actions)
        self.download_btn = QPushButton("下载选中点云")
        self.download_btn.clicked.connect(self.download_pointcloud)
        ah.addWidget(self.download_btn)
        self.status = QLabel("状态：未初始化")
        ah.addWidget(self.status)
        v.addWidget(actions)

        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("运行日志"))
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        right_layout.addWidget(self.log_box, 1)
        right_layout.addWidget(QLabel("总进度"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        right_layout.addWidget(self.progress)

    def append_log(self, text: str):
        self.log_box.appendPlainText(text)

    def init_runtime(self):
        key = self.api_key.text().strip()
        if not key:
            QMessageBox.warning(self, "提示", "API Key 必填")
            return

        try:
            self.progress.setValue(10)
            self.append_log("初始化开始：连接 DuckDB...")
            duck = DuckDBStore(self.db.text().strip())
            duck.init_schema()
            self.progress.setValue(30)
            self.append_log("DuckDB 初始化完成，连接 Qdrant...")
            qdrant = QdrantStore(self.qdrant.text().strip())
            qdrant.init_collection(dim=1024)
            self.progress.setValue(60)
            self.append_log("Qdrant 初始化完成，创建 embedder...")
            embedder = BGEEmbedder(api_key=key, model=self.model.text().strip() or "bge-m3")
            self.engine = SearchEngine(duck_store=duck, qdrant_store=qdrant, embedder=embedder)
            self.search_btn.setEnabled(True)
            self.status.setText("状态：已初始化")
            fields = [f["field"] for f in self.engine.supported_fields()]
            self.field.clear()
            self.field.addItems(fields)
            self.progress.setValue(100)
            self.append_log(f"初始化完成：已加载可筛选字段 {len(fields)} 个。")
        except Exception as e:
            self.progress.setValue(0)
            self.append_log(f"初始化失败：{e}")
            QMessageBox.critical(self, "初始化失败", str(e))

    def add_filter(self):
        field = self.field.currentText().strip()
        op = self.op.currentText().strip()
        value = self.value.text().strip()
        if not field or value == "":
            return
        row = self.filter_table.rowCount()
        self.filter_table.insertRow(row)
        self.filter_table.setItem(row, 0, QTableWidgetItem(field))
        self.filter_table.setItem(row, 1, QTableWidgetItem(op))
        self.filter_table.setItem(row, 2, QTableWidgetItem(value))

    def _filters(self) -> list[QueryFilter]:
        filters: list[QueryFilter] = []
        for r in range(self.filter_table.rowCount()):
            f = self.filter_table.item(r, 0)
            o = self.filter_table.item(r, 1)
            v = self.filter_table.item(r, 2)
            if not f or not o or not v:
                continue
            filters.append(QueryFilter(field=f.text(), op=o.text(), value=v.text()))
        return filters

    def remove_selected_filter(self):
        row = self.filter_table.currentRow()
        if row >= 0:
            self.filter_table.removeRow(row)

    def clear_filters(self):
        self.filter_table.setRowCount(0)

    def search(self):
        if self.engine is None:
            return
        try:
            self.progress.setValue(10)
            self.append_log(f"开始检索：query={self.query.text().strip()} top_k={int(self.topk.value())}")
            q = SearchQuery(
                semantic_query=self.query.text().strip(),
                target_component=infer_target_component(self.query.text().strip()),
                filters=self._filters(),
                top_k=int(self.topk.value()),
                strategy="semantic_first",
            )
            self.progress.setValue(35)
            self.append_log(f"筛选条件数：{len(q.filters)}")
            response = self.engine.search(q)
            self.progress.setValue(65)
            result = response["result"]
            display = present_results(result["results"], response["query"].filters)
            self.last_rows = display["rows"]

            columns = [c["key"] for c in display["columns"]]
            if "pointcloud_path" in columns:
                columns.remove("pointcloud_path")
                columns.insert(0, "pointcloud_path")
            self.result_table.setColumnCount(len(columns))
            self.result_table.setRowCount(len(display["rows"]))
            self.result_table.setHorizontalHeaderLabels(columns)
            for i, row in enumerate(display["rows"]):
                for j, c in enumerate(columns):
                    val = row.get(c)
                    self.result_table.setItem(i, j, QTableWidgetItem("" if val is None else str(val)))

            self.status.setText(f"状态：命中 {len(display['rows'])} 条，候选 {result['candidate_count']}，耗时 {result['elapsed_ms']}ms")
            self.progress.setValue(100)
            self.append_log(f"检索完成：命中 {len(display['rows'])} 条，候选 {result['candidate_count']}，耗时 {result['elapsed_ms']}ms")
        except Exception as e:
            self.progress.setValue(0)
            self.append_log(f"检索失败：{e}")
            QMessageBox.critical(self, "检索失败", str(e))

    def download_pointcloud(self):
        row_idx = self.result_table.currentRow()
        if row_idx < 0 or row_idx >= len(self.last_rows):
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        pc = self.last_rows[row_idx].get("pointcloud_path")
        if not pc:
            QMessageBox.warning(self, "提示", "该结果无点云文件")
            return
        src = Path(str(pc))
        if not src.exists():
            QMessageBox.warning(self, "提示", f"点云文件不存在：{src}")
            return
        dst, _ = QFileDialog.getSaveFileName(self, "保存点云", src.name)
        if not dst:
            return
        shutil.copyfile(src, dst)
        self.append_log(f"点云下载完成：{dst}")
        QMessageBox.information(self, "完成", f"已保存到：{dst}")


def main():
    app = QApplication([])
    w = SearchWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
