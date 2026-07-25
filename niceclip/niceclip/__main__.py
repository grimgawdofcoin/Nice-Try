"""Entry point: start the local server and open the UI in the browser."""

from __future__ import annotations

import argparse
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="niceclip",
        description="NiceClip — AI video clipper for social media (local web UI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true",
                        help="don't auto-open the web UI")
    args = parser.parse_args()

    import uvicorn

    from .server import create_app

    app = create_app()
    url = f"http://{args.host}:{args.port}"
    print(f"\n  NiceClip is running at {url}\n  Press Ctrl+C to quit.\n")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
