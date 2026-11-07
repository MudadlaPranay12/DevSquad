"""Convenience entry point: ``python -m bridge``.

Examples:
    python -m bridge                 # start on 127.0.0.1:8000
    python -m bridge --token         # print the local pairing token
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import ensure_pairing_token


def _configure_windows_event_loop() -> None:
    """Use the selector loop on Windows instead of the Proactor loop.

    The default ProactorEventLoop can abort its accept loop with
    ``OSError: [WinError 64] The specified network name is no longer
    available`` when a client disconnects abruptly, which silently kills the
    HTTP listener while the process stays alive. The bridge does not use
    asyncio subprocesses (Playwright and OpenCode run in worker threads), so
    the selector loop is safe here and remains stable under polling clients.
    """
    if sys.platform != "win32":
        return
    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is not None:
        asyncio.set_event_loop_policy(policy())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEV-SQUAD evidence bridge")
    parser.add_argument("--token", action="store_true", help="Print the pairing token and exit.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000).")
    args = parser.parse_args(argv)

    if args.token:
        print(ensure_pairing_token())
        return 0

    import uvicorn

    _configure_windows_event_loop()
    uvicorn.run(
        "bridge.bridge:app",
        host=args.host,
        port=args.port,
        log_level="info",
        loop="asyncio",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
