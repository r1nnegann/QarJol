"""QarJol web interface - local server (standard library only, Python 3.9+).

Run:   python app.py                # opens http://127.0.0.1:8765 in the browser
       python app.py --port 9000    # another port
       python app.py --no-browser   # do not open a browser tab

The page in web/ asks this server for results; the server calls the same
qarjol functions that main.py prints. Nothing has to be installed and no
internet connection is needed. Stop the server with Ctrl+C.
"""

import argparse
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from qarjol import web_api

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(ROOT, "web")
PACKAGE_DIR = os.path.join(ROOT, "qarjol")

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/plain; charset=utf-8", ".py")


def _one(query, name, default=None):
    values = query.get(name)
    return values[0] if values else default


def handle_api(path, query):
    """Return (status, payload) for an /api/... request."""
    if path == "/api/health":
        return HTTPStatus.OK, {"ok": True, "engine": "python-server",
                               "python": sys.version.split()[0]}
    if path == "/api/scenario":
        return HTTPStatus.OK, web_api.scenario(
            prior=float(_one(query, "prior", 0.30)),
            plow=float(_one(query, "plow", 0.50)),
            readings=_one(query, "readings", ""))
    if path == "/api/evaluate":
        prior, plow = _one(query, "prior"), _one(query, "plow")
        return HTTPStatus.OK, web_api.evaluate(
            mornings=int(_one(query, "mornings", 10_000)),
            prior=None if prior is None else float(prior),
            plow=None if plow is None else float(plow))
    if path == "/api/random":
        seed = _one(query, "seed")
        return HTTPStatus.OK, web_api.random_morning(
            prior=float(_one(query, "prior", 0.30)),
            plow=float(_one(query, "plow", 0.50)),
            seed=None if seed in (None, "") else int(seed))
    return HTTPStatus.NOT_FOUND, {"error": f"unknown endpoint {path}"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            try:
                status, payload = handle_api(url.path, parse_qs(url.query))
            except (TypeError, ValueError) as exc:
                status, payload = HTTPStatus.BAD_REQUEST, {"error": str(exc)}
            self._send_json(status, payload)
            return
        super().do_GET()

    def translate_path(self, path):
        # /qarjol/*.py comes from the package itself (used by the in-browser engine).
        clean = urlparse(path).path
        if clean.startswith("/qarjol/") and clean.endswith(".py"):
            name = os.path.basename(clean)
            return os.path.join(PACKAGE_DIR, name)
        return super().translate_path(path)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two servers share a port; keep ports exclusive there.
    allow_reuse_address = os.name != "nt"


def make_server(host, port, tries=10):
    last = None
    for p in range(port, port + tries):
        try:
            return Server((host, p), Handler)
        except OSError as exc:  # port busy: try the next one
            last = exc
    raise SystemExit(f"Could not open a port from {port} to {port + tries - 1}: {last}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    server = make_server(args.host, args.port)
    url = f"http://{args.host}:{server.server_address[1]}/"
    print("QarJol web interface (A* + Bayes + MDP)")
    print(f"Open {url}   (Ctrl+C stops the server)")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
