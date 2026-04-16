"""
Minimal static file server for the JABchem preview.
Usage: python preview_server.py <site_dir> <port>
Serves <site_dir> on 0.0.0.0:<port>, resolving /foo/ → /foo/index.html.
"""

import sys
import os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler


class PreviewHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Let the base class resolve the filesystem path
        fs_path = super().translate_path(path)
        p = Path(fs_path)
        # If it's a directory, look for index.html inside it
        if p.is_dir():
            candidate = p / 'index.html'
            if candidate.is_file():
                return str(candidate)
        return fs_path

    def log_message(self, fmt, *args):
        pass  # suppress access logs


if __name__ == '__main__':
    site_dir, port = sys.argv[1], int(sys.argv[2])
    os.chdir(site_dir)
    server = HTTPServer(('0.0.0.0', port), PreviewHandler)
    server.serve_forever()
