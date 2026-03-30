"""Local bridge for frontend demos.

- POST /api/builder/run      启动 builder_tool(.exe) 任务
- GET  /api/builder/status   查看执行状态与日志

仅用于本地联调示例，不建议直接用于生产。
"""
from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 18081

process_lock = threading.Lock()
current_process: subprocess.Popen | None = None
log_buffer: list[str] = []
last_exit_code: int | None = None


def _append_log(line: str):
    with process_lock:
        log_buffer.append(line.rstrip("\n"))
        if len(log_buffer) > 500:
            del log_buffer[:-500]


def _stream_output(proc: subprocess.Popen):
    global last_exit_code, current_process
    assert proc.stdout is not None
    for line in proc.stdout:
        _append_log(line)
    proc.wait()
    with process_lock:
        last_exit_code = proc.returncode
        current_process = None


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._json(200, {"ok": True})

    def do_GET(self):
        if self.path != "/api/builder/status":
            return self._json(404, {"error": "not found"})

        with process_lock:
            running = current_process is not None
            payload = {
                "running": running,
                "exit_code": last_exit_code,
                "logs": list(log_buffer),
            }
        return self._json(200, payload)

    def do_POST(self):
        if self.path != "/api/builder/run":
            return self._json(404, {"error": "not found"})

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")

        config_path = str(payload.get("config_path") or "config.yaml").strip()
        run_mode = str(payload.get("run_mode") or "full").strip()
        executable = str(payload.get("builder_executable") or "dist/builder_tool.exe").strip()

        exe_path = Path(executable).resolve()
        if exe_path.name.lower() not in {"builder_tool.exe", "builder_tool.py"}:
            return self._json(400, {"error": "builder_executable 不在白名单中"})

        with process_lock:
            global current_process, last_exit_code
            if current_process is not None:
                return self._json(409, {"error": "已有任务正在运行"})
            log_buffer.clear()
            last_exit_code = None

            cmd = [str(exe_path), "--config", config_path, "--run-mode", run_mode]
            if exe_path.suffix.lower() == ".py":
                cmd = ["python", str(exe_path), "--config", config_path, "--run-mode", run_mode]

            current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(Path.cwd()),
            )
            threading.Thread(target=_stream_output, args=(current_process,), daemon=True).start()

        return self._json(200, {"ok": True, "message": "任务已启动"})


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    print(f"bridge listening on http://{HOST}:{PORT}")
    server.serve_forever()
