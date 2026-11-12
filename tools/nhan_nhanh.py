#!/usr/bin/env python3
"""Máy nhận dữ liệu Nhanh trên máy này (127.0.0.1:8765): nhanh_sync.js chạy trong Chrome của chủ shop POST JSON vào
đây, ghi thẳng cache logs/nhanh/ (thay cho file tải về). Chỉ nghe localhost, cần mã TOKEN trong ~/.config/orbit-kho/nhanh_token."""
import json, os, secrets, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nhanh as NH

TF = os.path.expanduser("~/.config/orbit-kho/nhanh_token")
if not os.path.exists(TF):
    open(TF, "w").write(secrets.token_hex(16)); os.chmod(TF, 0o600)
TOKEN = open(TF).read().strip()


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "https://nhanh.vn")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Orbit-Token")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_POST(self):
        if self.headers.get("X-Orbit-Token") != TOKEN:
            self.send_response(403); self._cors(); self.end_headers(); return
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        m = NH.meta() or {}
        m.setdefault("bat_dau", d["dong_bo"])
        m.update(dong_bo=d["dong_bo"], so_sp=len(d["products"]), so_don=len(d["orders"]), loi="", nguon="chrome")
        NH._ghi("products.json", d["products"]); NH._ghi("orders.json", d["orders"]); NH._ghi("meta.json", m)
        self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b"OK")
        print("nhận", m["dong_bo"], m["so_sp"], m["so_don"], flush=True)
        NH.sau_sync()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
