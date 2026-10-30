"""Sirve la UI simulada con la biblioteca estándar, sin importar la aplicación."""
from argparse import ArgumentParser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class OfflineHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/offline", "/offline/"):
            if path == "/":
                self.send_response(302)
                self.send_header("Location", "/offline")
                self.end_headers()
                return
            self.path = "/index.html"
        elif path.startswith("/public/"):
            self.path = self.path[len("/public"):]
        else:
            self.send_error(404)
            return
        super().do_GET()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    public = Path(__file__).resolve().parent / "public"
    server = ThreadingHTTPServer((args.bind, args.port), partial(OfflineHandler, directory=str(public)))
    print(f"UI simulada: http://{args.bind}:{args.port}/offline", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
