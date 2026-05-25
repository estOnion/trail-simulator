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
from .api.ws_steps import build_ws_steps_router
from .config import FRONTEND_DIR, SETTINGS
from .device.developer_mode import preflight
from .device.location import LocationClient
from .device.multi_location import MultiLocationClient
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
                await controller.reset_device()
            except Exception:
                pass

    app = FastAPI(title="Trail Simulator", lifespan=lifespan)
    app.include_router(build_router(controller), prefix="/api")
    app.include_router(build_ws_router(controller))
    app.include_router(build_ws_steps_router())

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
    parser.add_argument(
        "--port",
        type=int,
        default=SETTINGS.port,
        help="HTTP/WebSocket port. Avoid ports the iOS device tunnel uses: binding "
             "8787 has been observed to collide with the pymobiledevice3/RSD tunnel "
             "(tunneld stream resets, error_code=5 → GPS won't spoof). Use e.g. 8080.",
    )
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
    parser.add_argument(
        "--udid",
        action="append",
        default=None,
        help="Target a specific iPhone by UDID. Repeat to mirror to multiple devices "
             "(e.g., --udid AAA --udid BBB). With no --udid, exactly one device must be connected.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.host != "127.0.0.1":
        log.warning("binding to %s — reachable from LAN (no auth)", args.host)

    # Port 8787 has been observed to collide with the iOS device tunnel
    # (pymobiledevice3/RSD): the tunneld HTTP/2 stream gets reset
    # (error_code=5) and GPS injection silently fails. Warn when targeting a
    # real device on that port; pick another (e.g. --port 8080) if it stalls.
    if args.port == 8787 and not args.dev_no_device:
        log.warning(
            "port 8787 can collide with the iOS device tunnel (RSD); "
            "if GPS won't spoof, retry with --port 8080"
        )

    requested_udids: list[str] = list(args.udid) if args.udid else []
    resolved_udids: list[str | None] = []

    if not args.dev_no_device:
        if not requested_udids:
            pf = preflight(udid=None)
            print(f"[preflight] {pf.message}")
            if not pf.ok:
                print("[preflight] FAILED — fix above, or run with --dev-no-device to preview the UI.", file=sys.stderr)
                return 2
            resolved_udids = [pf.udid]
        else:
            for u in requested_udids:
                pf = preflight(udid=u)
                print(f"[preflight] {pf.message}")
                if not pf.ok:
                    print("[preflight] FAILED — fix above, or run with --dev-no-device to preview the UI.", file=sys.stderr)
                    return 2
            resolved_udids = list(requested_udids)

        if not tunneld_reachable():
            print("[tunneld] NOT RUNNING", file=sys.stderr)
            print(start_instructions(), file=sys.stderr)
            return 3
        print("[tunneld] reachable at 127.0.0.1:49151")
    else:
        print("[preflight] SKIPPED (--dev-no-device) — GPS injection is stubbed.")
        resolved_udids = [requested_udids[0] if requested_udids else None]

    store = Store()
    if args.dev_no_device:
        device = _StubLocation(udid=resolved_udids[0])
    elif len(resolved_udids) > 1:
        device = MultiLocationClient([u for u in resolved_udids if u is not None])
        print(f"[devices] mirror mode active for {len(resolved_udids)} devices")
    else:
        device = LocationClient(udid=resolved_udids[0])
    controller = SessionController(device, store)
    from .api.ws_steps import broadcaster as _step_broadcaster
    _step_broadcaster.set_change_callback(controller._broadcast)
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
