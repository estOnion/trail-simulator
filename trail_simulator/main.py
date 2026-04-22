from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.rest import build_router
from .api.ws import build_ws_router
from .config import FRONTEND_DIR, SETTINGS
from .device.developer_mode import preflight
from .device.location import LocationClient
from .device.tunneld import start_instructions, tunneld_reachable
from .session.controller import SessionController
from .session.store import Store


log = logging.getLogger("trail_simulator")


class _StubLocation(LocationClient):
    """No-op device for --dev-no-device mode: lets the tick loop run so the
    browser UI can be exercised without a plugged-in iPhone."""

    async def open(self) -> None:  # noqa: D401
        log.info("[stub] device open()")

    async def set(self, lat: float, lon: float) -> None:
        pass

    async def clear(self) -> None:
        log.info("[stub] device clear()")


def build_app(controller: SessionController) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            try:
                await controller.stop()
            except Exception:
                pass

    app = FastAPI(title="Trail Simulator", lifespan=lifespan)
    app.include_router(build_router(controller), prefix="/api")
    app.include_router(build_ws_router(controller))

    if FRONTEND_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(FRONTEND_DIR)),
            name="static",
        )

        @app.get("/")
        async def index():
            return FileResponse(FRONTEND_DIR / "index.html")

    return app


def main() -> int:
    parser = argparse.ArgumentParser(prog="trail_simulator")
    parser.add_argument("--host", default=SETTINGS.host)
    parser.add_argument("--port", type=int, default=SETTINGS.port)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the browser.",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
    )
    parser.add_argument(
        "--dev-no-device",
        action="store_true",
        help="Skip preflight + use a stub device (UI preview only; no GPS injection).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.host != "127.0.0.1":
        log.warning("binding to %s — reachable from LAN (no auth)", args.host)

    if not args.dev_no_device:
        pf = preflight()
        print(f"[preflight] {pf.message}")
        if not pf.ok:
            print("[preflight] FAILED — fix above, or run with --dev-no-device to preview the UI.", file=sys.stderr)
            return 2

        if not tunneld_reachable():
            print("[tunneld] NOT RUNNING", file=sys.stderr)
            print(start_instructions(), file=sys.stderr)
            return 3
        print("[tunneld] reachable at 127.0.0.1:49151")
    else:
        print("[preflight] SKIPPED (--dev-no-device) — GPS injection is stubbed.")

    store = Store()
    device: LocationClient = _StubLocation() if args.dev_no_device else LocationClient()
    controller = SessionController(device, store)
    app = build_app(controller)

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    print(f"[trail-simulator] UI at {url}")

    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
