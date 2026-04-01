from __future__ import annotations

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os


PORT = 8612
SHOWCASE_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "showcase" / "latest"


def main() -> None:
    if not SHOWCASE_DIR.exists():
        raise FileNotFoundError(f"Showcase directory does not exist: {SHOWCASE_DIR}")

    os.chdir(SHOWCASE_DIR)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), SimpleHTTPRequestHandler)
    print(f"Serving showcase at http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
