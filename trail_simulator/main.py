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
from .device.android import android_sdk_int, list_android_devices
from .device.android_location import AndroidLocationClient
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


def _make_device_factory(android_serials: set[str]):
    """Dispatch each opaque device key to the right adapter: ADB serials in
    `android_serials` → AndroidLocationClient, everything else → iOS."""
    android = set(android_serials)

    def _factory(key: str):
        if key in android:
            return AndroidLocationClient(key)
        return LocationClient(udid=key)

    return _factory


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
        "--android",
        action="append",
        default=None,
        help="Target a rooted Android 12+ phone by adb serial (see `adb devices`). "
             "Repeat for multiple. Injects GPS via `cmd location` over adb — no app "
             "on the phone. Can be combined with --udid for a mixed device set.",
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
    android_serials: list[str] = list(args.android) if args.android else []
    resolved_udids: list[str | None] = []
    android_devices: list[tuple[str, str]] = []  # (serial, model name)

    if args.mirror and android_serials:
        print("[error] --mirror is iOS-only and can't be combined with --android.",
              file=sys.stderr)
        return 2

    if not args.dev_no_device:
        # iOS preflight only when iPhones are in play. With --android and no
        # --udid, run Android-only and skip the iOS tunnel entirely.
        ios_in_play = bool(requested_udids) or not android_serials
        if ios_in_play:
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

        # Android preflight: each serial must be online and API >= 31.
        if android_serials:
            try:
                online = dict(asyncio.run(list_android_devices()))
            except Exception as e:  # noqa: BLE001
                print(f"[android] adb error: {e}", file=sys.stderr)
                return 2
            for serial in android_serials:
                if serial not in online:
                    avail = ", ".join(online) or "none"
                    print(f"[android] {serial} not online via adb (available: {avail}).",
                          file=sys.stderr)
                    return 2
                sdk = asyncio.run(android_sdk_int(serial))
                if sdk < 31:
                    print(f"[android] {serial} is API {sdk}; need Android 12+ (API 31) "
                          "for app-free `cmd location` injection.", file=sys.stderr)
                    return 2
                android_devices.append((serial, online[serial]))
                print(f"[android] {serial} ready (API {sdk}, {online[serial]})")
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
        # Default: one SessionController per device (iOS + Android), parallel.
        # iOS devices are named from lockdown DeviceName; Android from getprop.
        for u in resolved_udids:
            if u is None:
                continue
            try:
                name = asyncio.run(fetch_device_name(u))
            except Exception as e:  # noqa: BLE001
                log.warning("could not read DeviceName for %s, using UDID: %s", u, e)
                name = u
            registry.register(udid=u, name=name)
        for serial, name in android_devices:
            registry.register(udid=serial, name=name, device_type="android")
        manager = SessionManager(
            device_factory=_make_device_factory({s for s, _ in android_devices}),
            store=store,
        )
    total = len([u for u in resolved_udids if u is not None]) + len(android_devices)
    if total > 1 and not args.mirror:
        names = ", ".join(n for _, n in registry.list_devices())
        print(f"[devices] parallel session mode for {total} devices: {names}")

    from .api.ws_steps import broadcaster as _step_broadcaster

    async def _on_step_clients_change() -> None:
        await asyncio.gather(*[c._broadcast() for _, c in manager.list_active()])

    _step_broadcaster.set_change_callback(_on_step_clients_change)
    _step_broadcaster.set_registry(registry)
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
