from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QCheckBox,
    QWidget,
    QProgressBar,
)

from builder_tool import run_builder


class LogBridge(QObject):
    line = Signal(str)
    build_finished = Signal(bool, bool, str)
    progress = Signal(str, int, int, str)


class BuilderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("建库工具（PySide6）")
        self.resize(980, 700)

        self.log_bridge = LogBridge()
        self.log_bridge.line.connect(self.append_log)
        self.log_bridge.build_finished.connect(self.on_build_finished)
        self.log_bridge.progress.connect(self.on_progress)

        self.worker: threading.Thread | None = None
        self.watching = False
        self.file_snapshot: dict[str, float] = {}

        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        left = QWidget()
        right = QWidget()
        layout.addWidget(left, 2)
        layout.addWidget(right, 3)

        form = QFormLayout(left)

        self.model_edit = QLineEdit("bge-m3")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.db_edit = QLineEdit(str(Path("db/bom.duckdb").resolve()))
        self.qdrant_edit = QLineEdit(str(Path("db/qdrant_storage").resolve()))
        self.bom_edit = QLineEdit(str(Path("data/bom").resolve()))
        self.pc_edit = QLineEdit(str(Path("data/pointcloud").resolve()))

        form.addRow("Embedding模型", self.model_edit)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("DuckDB路径", self._path_row(self.db_edit, is_file=True))
        form.addRow("Qdrant路径", self._path_row(self.qdrant_edit, is_file=False))
        form.addRow("BOM文件夹", self._path_row(self.bom_edit, is_file=False))
        form.addRow("点云文件夹", self._path_row(self.pc_edit, is_file=False))

        self.watch_check = QCheckBox("建库完成后持续监控新增文件并自动增量更新")
        self.watch_check.setChecked(True)
        form.addRow(self.watch_check)

        self.run_btn = QPushButton("一键建库")
        self.run_btn.clicked.connect(self.start_build)
        self.stop_watch_btn = QPushButton("停止监控")
        self.stop_watch_btn.clicked.connect(self.stop_watch)
        self.stop_watch_btn.setEnabled(False)
        form.addRow(self.run_btn, self.stop_watch_btn)

        self.status_lbl = QLabel("状态：待命")
        form.addRow(self.status_lbl)

        right_layout = QHBoxLayout(right)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        right_layout.addWidget(self.log)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        form.addRow("总进度", self.progress)

        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(5000)
        self.watch_timer.timeout.connect(self.tick_watch)

    def _path_row(self, edit: QLineEdit, is_file: bool):
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(edit)
        btn = QPushButton("选择")

        def choose():
            if is_file:
                path, _ = QFileDialog.getSaveFileName(self, "选择文件", edit.text())
                if path:
                    edit.setText(path)
            else:
                path = QFileDialog.getExistingDirectory(self, "选择目录", edit.text())
                if path:
                    edit.setText(path)

        btn.clicked.connect(choose)
        hl.addWidget(btn)
        return box

    def append_log(self, text: str):
        self.log.appendPlainText(text)

    def cfg(self) -> dict:
        return {
            "storage": {
                "duckdb_path": self.db_edit.text().strip(),
                "qdrant_path": self.qdrant_edit.text().strip(),
                "vector_dim": 1024,
            },
            "input": {
                "bom_folder": self.bom_edit.text().strip(),
                "pointcloud_root": self.pc_edit.text().strip(),
            },
            "builder": {
                "header_candidate_rows": [0, 1],
                "min_header_score": 1,
                "drop_unnamed_columns": True,
                "fail_report_path": "output/fail_report.csv",
                "run_mode": "incremental",
            },
            "pointcloud": {
                "extensions": [".stl", ".obj"],
            },
            "embedding": {
                "enabled": True,
                "api_key": self.api_key_edit.text().strip(),
                "model": self.model_edit.text().strip() or "bge-m3",
            },
        }

    def start_build(self):
        if self.worker and self.worker.is_alive():
            QMessageBox.warning(self, "提示", "建库任务正在运行")
            return

        self.run_btn.setEnabled(False)
        self.status_lbl.setText("状态：建库中...")
        cfg = self.cfg()
        self.log_bridge.line.emit("开始建库...")
        self.progress.setValue(0)

        def job():
            try:
                run_builder(cfg, progress_cb=lambda s, c, t, n: self.log_bridge.progress.emit(s, c, t, n))
                self.log_bridge.line.emit("建库完成。")
                self.log_bridge.build_finished.emit(True, self.watch_check.isChecked(), "")
            except Exception as e:
                self.log_bridge.line.emit(f"建库失败：{e}")
                self.log_bridge.build_finished.emit(False, False, str(e))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def on_build_finished(self, ok: bool, should_watch: bool, error: str):
        self.run_btn.setEnabled(True)
        if not ok:
            self.status_lbl.setText("状态：失败")
            self.progress.setValue(0)
            return
        if should_watch:
            self.start_watch()
        else:
            self.status_lbl.setText("状态：建库完成")
            self.progress.setValue(100)

    def on_progress(self, stage: str, current: int, total: int, name: str):
        if stage == "bom_total":
            self.append_log(f"BOM 总待处理文件：{total}")
            return
        if stage == "pointcloud_total":
            self.append_log(f"点云总待处理文件：{total}")
            return
        if stage == "bom_processing":
            self.append_log(f"[BOM] 当前处理：{current}/{max(total, 1)} -> {name}")
            self.progress.setValue(int((current / max(total, 1)) * 70))
            return
        if stage == "pointcloud_processing":
            self.append_log(f"[点云] 当前处理：{current}/{max(total, 1)} -> {name}")
            self.progress.setValue(70 + int((current / max(total, 1)) * 30))
            return
        if stage == "done":
            self.progress.setValue(100)

    def _scan_snapshot(self) -> dict[str, float]:
        snap: dict[str, float] = {}
        bom_root = Path(self.bom_edit.text().strip())
        pc_root = Path(self.pc_edit.text().strip())
        for root, patterns in ((bom_root, ("*.xlsx", "*.xls", "*.csv")), (pc_root, ("*.stl", "*.obj"))):
            if not root.exists():
                continue
            for pat in patterns:
                for fp in root.rglob(pat):
                    try:
                        snap[str(fp.resolve())] = fp.stat().st_mtime
                    except OSError:
                        pass
        return snap

    def start_watch(self):
        self.file_snapshot = self._scan_snapshot()
        self.watching = True
        self.watch_timer.start()
        self.stop_watch_btn.setEnabled(True)
        self.status_lbl.setText("状态：监控中")
        self.log_bridge.line.emit("已开启文件夹监控（每5秒扫描一次）")

    def stop_watch(self):
        self.watching = False
        self.watch_timer.stop()
        self.stop_watch_btn.setEnabled(False)
        self.status_lbl.setText("状态：已停止监控")
        self.log_bridge.line.emit("监控已停止")

    def tick_watch(self):
        if not self.watching or (self.worker and self.worker.is_alive()):
            return

        latest = self._scan_snapshot()
        changed = []
        for k, m in latest.items():
            if k not in self.file_snapshot or self.file_snapshot[k] < m:
                changed.append(k)

        if not changed:
            return

        self.file_snapshot = latest
        self.log_bridge.line.emit(f"检测到新增/变更文件 {len(changed)} 个，执行增量更新...")
        cfg = self.cfg()

        def job():
            try:
                run_builder(cfg)
                self.log_bridge.line.emit("增量更新完成。")
            except Exception as e:
                self.log_bridge.line.emit(f"增量更新失败：{e}")

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()


def main():
    app = QApplication([])
    w = BuilderWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
