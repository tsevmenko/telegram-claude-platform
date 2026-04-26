"""Telegram <-> Claude Code gateway.

Routes Telegram messages to Claude Code CLI sessions per agent. Built on
aiogram for Telegram and `claude` CLI subprocesses with stream-json parsing
for live progress rendering.
"""

__version__ = "0.0.1"
