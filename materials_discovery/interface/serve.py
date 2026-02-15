"""Dev server that serves index.html for all non-file routes (SPA fallback)."""
import http.server
import os

PORT = 8080
DIR = os.path.dirname(os.path.abspath(__file__))


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_GET(self):
        path = self.translate_path(self.path)
        if os.path.isfile(path):
            return super().do_GET()
        self.path = "/index.html"
        return super().do_GET()


if __name__ == "__main__":
    with http.server.HTTPServer(("", PORT), SPAHandler) as httpd:
        print(f"Serving on http://localhost:{PORT}")
        httpd.serve_forever()
