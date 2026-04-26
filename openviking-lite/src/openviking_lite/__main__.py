"""CLI entry point: ``openviking-lite serve --listen 127.0.0.1:1933 --data-dir /var/lib/openviking``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from openviking_lite.server import serve


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="openviking-lite")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the HTTP server.")
    s.add_argument("--listen", default="127.0.0.1:1933",
                   help="host:port to bind (default 127.0.0.1:1933, loopback only).")
    s.add_argument("--data-dir", default="/var/lib/openviking",
                   help="Directory for the SQLite file.")
    s.add_argument("--key-file", default="/etc/openviking/key",
                   help="Path to the API key file (read at startup).")
    s.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s openviking-lite: %(message)s",
    )

    if args.cmd == "serve":
        host, _, port = args.listen.rpartition(":")
        host = host or "127.0.0.1"
        data_dir = Path(args.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "openviking.db"
        key_path = Path(args.key_file)
        try:
            serve(host=host, port=int(port), db_path=db_path, key_path=key_path)
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
