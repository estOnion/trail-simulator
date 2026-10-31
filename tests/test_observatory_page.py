"""The observatory page is served next to the web UI (HST-18)."""
from __future__ import annotations

from fastapi.testclient import TestClient

import trail_simulator.main as main_mod
from trail_simulator.device.registry import DeviceRegistry
from trail_simulator.main import build_app
from trail_simulator.session.manager import SessionManager
from trail_simulator.session.store import Store


def _client(tmp_path):
    manager = SessionManager(device_factory=lambda u: object(), store=Store(tmp_path / "s.db"))
    return TestClient(build_app(manager, DeviceRegistry()))


def test_observatory_page_is_served(tmp_path):
    client = _client(tmp_path)

    r = client.get("/observatory")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Observatory" in r.text
    assert "/static/observatory.js" in r.text


def test_observatory_assets_are_served_under_static(tmp_path):
    client = _client(tmp_path)
    assert client.get("/static/observatory.js").status_code == 200
    assert client.get("/static/observatory.css").status_code == 200


def test_web_ui_links_to_the_observatory(tmp_path):
    client = _client(tmp_path)
    assert 'href="/observatory"' in client.get("/").text


def test_neither_page_is_served_when_the_frontend_folder_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "FRONTEND_DIR", tmp_path / "missing")
    client = _client(tmp_path)

    assert client.get("/").status_code == 404
    assert client.get("/observatory").status_code == 404
