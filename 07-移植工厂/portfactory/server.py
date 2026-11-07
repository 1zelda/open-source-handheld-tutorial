from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import db, engine
from .models import job_state_label
from .report import render_job_html


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>
body{{font:14px/1.6 system-ui,Segoe UI,Microsoft YaHei;margin:32px;max-width:1100px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #d8dee9;padding:6px 8px}}
th{{background:#f3f5f8}} a{{color:#1557a0}} code{{font-size:12px}}
</style><h1>{title}</h1>{body}""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    factory = None

    def log_message(self, fmt, *args):
        return

    def _send(self, body: bytes, code: int = 200, kind: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            with self.factory.connect() as conn:
                jobs = db.list_jobs(conn)
            rows = "".join(
                f"<tr><td><a href='/job/{j['id']}'>{j['id']}</a></td>"
                f"<td>{j.get('game_name') or '-'}</td><td>{j.get('device_name') or '-'}</td>"
                f"<td>{j['recipe_id']}</td><td>{job_state_label(j['status'])}</td>"
                f"<td>{j['updated_at']}</td></tr>"
                for j in jobs) or "<tr><td colspan='6'>暂无任务</td></tr>"
            return self._send(_page(
                "移植工厂",
                f"<p><a href='/api/jobs'>JSON</a></p><table><tr><th>任务</th><th>游戏</th>"
                f"<th>设备</th><th>配方</th><th>状态</th><th>更新时间（UTC）</th></tr>{rows}</table>"))
        if path.startswith("/job/"):
            job_id = path.split("/", 2)[2]
            with self.factory.connect() as conn:
                try:
                    summary = engine.job_summary(conn, job_id)
                except engine.EngineError:
                    return self._send(b"not found", 404, "text/plain; charset=utf-8")
            return self._send(render_job_html(summary).encode("utf-8"))
        if path == "/api/jobs":
            with self.factory.connect() as conn:
                payload = db.list_jobs(conn)
            return self._send(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                              200, "application/json; charset=utf-8")
        if path.startswith("/api/job/"):
            job_id = path.split("/", 3)[3]
            with self.factory.connect() as conn:
                try:
                    payload = engine.job_summary(conn, job_id)
                except engine.EngineError:
                    return self._send(b'{"error":"not found"}', 404,
                                      "application/json; charset=utf-8")
            return self._send(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                              200, "application/json; charset=utf-8")
        self._send(b"not found", 404, "text/plain; charset=utf-8")


def serve(factory, host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = type("FactoryHandler", (Handler,), {"factory": factory})
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"看板：http://{host}:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
