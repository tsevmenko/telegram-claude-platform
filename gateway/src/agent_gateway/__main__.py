"""CLI entry point: ``python -m agent_gateway --config /path/to/config.json``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from agent_gateway.config import GatewayConfig
from agent_gateway.multi_agent import MultiAgentGateway


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent-gateway")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to gateway config.json",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = GatewayConfig.load(args.config)
    gateway = MultiAgentGateway(config)
    gateway.setup()

    try:
        asyncio.run(gateway.run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
