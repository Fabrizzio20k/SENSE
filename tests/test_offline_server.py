import unittest
from http.server import SimpleHTTPRequestHandler
from unittest.mock import Mock, patch

from serve_offline import OfflineHandler


class OfflineServerTests(unittest.TestCase):
    def handler(self, path):
        handler = OfflineHandler.__new__(OfflineHandler)
        handler.path = path
        for name in ("send_response", "send_header", "end_headers", "send_error"):
            setattr(handler, name, Mock())
        return handler

    def test_routes_only_serve_the_shared_ui_and_public_assets(self):
        with patch.object(SimpleHTTPRequestHandler, "do_GET") as serve:
            for path, target in (("/offline", "/index.html"), ("/offline/", "/index.html"),
                                 ("/public/app.js?v=1", "/app.js?v=1")):
                handler = self.handler(path)
                handler.do_GET()
                self.assertEqual(handler.path, target)
            self.assertEqual(serve.call_count, 3)
            handler = self.handler("/api/experiments/start")
            handler.do_GET()
            handler.send_error.assert_called_once_with(404)
            self.assertEqual(serve.call_count, 3)

    def test_root_redirects_to_the_explicit_offline_mode(self):
        handler = self.handler("/")
        handler.do_GET()
        handler.send_response.assert_called_once_with(302)
        handler.send_header.assert_called_once_with("Location", "/offline")


if __name__ == "__main__":
    unittest.main()
