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
from .device.registry import DeviceRegistry, fetch_device_name
from .device.tunneld import start_instructions, tunneld_reachable
from .session.controller import SessionController
from .session.manager import SessionManager
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


def build_app(manager: SessionManager, registry: DeviceRegistry) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            try:
                await manager.stop_all()
            except Exception:
                pass

    app = FastAPI(title="Trail Simulator", lifespan=lifespan)
    app.include_router(build_router(manager, registry), prefix="/api")
    app.include_router(build_ws_router(manager, registry))
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
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="Mirror one session across all --udid devices (legacy fan-out). "
             "Default is parallel sessions — each --udid runs an independent "
             "session, addressed by the iPhone's DeviceName.",
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
    registry = DeviceRegistry()

    if args.dev_no_device:
        # Stub: register a single fake device named after this Mac.
        import socket
        fake_udid = resolved_udids[0] or "DEV-STUB"
        registry.register(udid=fake_udid, name=socket.gethostname())
        def _factory(udid):
            return _StubLocation(udid=udid)
        manager = SessionManager(device_factory=_factory, store=store)
    elif args.mirror and len(resolved_udids) > 1:
        # Legacy mirror mode: one controller, MultiLocationClient across N devices.
        mirror_udids = [u for u in resolved_udids if u is not None]
        primary_udid = mirror_udids[0]
        try:
            primary_name = asyncio.run(fetch_device_name(primary_udid))
        except Exception:  # noqa: BLE001
            primary_name = primary_udid
        registry.register(udid=primary_udid, name=primary_name)
        mirror_client = MultiLocationClient(mirror_udids)
        def _factory(udid):  # returns the shared mirror client regardless of udid
            return mirror_client
        manager = SessionManager(device_factory=_factory, store=store)
        print(f"[devices] mirror mode active for {len(resolved_udids)} devices")
    else:
        # Default: one SessionController per UDID. Build the registry by
        # asking each device for its DeviceName.
        for u in resolved_udids:
            if u is None:
                continue
            try:
                name = asyncio.run(fetch_device_name(u))
            except Exception as e:  # noqa: BLE001
                log.warning("could not read DeviceName for %s, using UDID: %s", u, e)
                name = u
            registry.register(udid=u, name=name)
        def _factory(udid):
            return LocationClient(udid=udid)
        manager = SessionManager(device_factory=_factory, store=store)
    if len(resolved_udids) > 1 and not args.mirror:
        names = ", ".join(n for _, n in registry.list_devices())
        print(f"[devices] parallel session mode for {len(resolved_udids)} "
              f"devices: {names}")

    from .api.ws_steps import broadcaster as _step_broadcaster

    async def _on_step_clients_change() -> None:
        await asyncio.gather(*[c._broadcast() for _, c in manager.list_active()])

    _step_broadcaster.set_change_callback(_on_step_clients_change)
    app = build_app(manager, registry)

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
