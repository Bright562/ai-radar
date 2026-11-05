"""本地预览服务器（零依赖）：python scripts/serve.py [端口]"""
import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".json": "application/json; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # 数据文件随时更新，禁用启发式缓存
        super().end_headers()

    def log_message(self, fmt, *args):  # 安静一点
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"AI 雷达已启动: http://localhost:{port}  (Ctrl+C 退出)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("已停止")


if __name__ == "__main__":
    main()
