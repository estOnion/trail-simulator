import os
import signal
import socket
import subprocess
import sys
import textwrap
import time

import pytest

from trail_simulator import main as main_mod
from trail_simulator.main import _free_stale_port


class _Run:
    """Stand-in for subprocess.run that replays canned stdout per command."""

    def __init__(self, lsof_outputs, ps_output="python -m trail_simulator"):
        self.lsof_outputs = list(lsof_outputs)
        self.ps_output = ps_output
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == "lsof":
            out = self.lsof_outputs.pop(0) if self.lsof_outputs else ""
        else:
            out = self.ps_output
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


@pytest.fixture
def killed(monkeypatch):
    """Record signals sent instead of actually delivering them."""
    sent = []
    monkeypatch.setattr(main_mod.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(main_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(main_mod.os, "name", "posix")
    return sent


def test_noop_off_posix(monkeypatch, killed):
    monkeypatch.setattr(main_mod.os, "name", "nt")
    run = _Run(["999"])
    monkeypatch.setattr(main_mod.subprocess, "run", run)

    _free_stale_port(8080)

    assert run.calls == []
    assert killed == []


def test_no_listener_kills_nothing(monkeypatch, killed):
    monkeypatch.setattr(main_mod.subprocess, "run", _Run([""]))

    _free_stale_port(8080)

    assert killed == []


def test_terminates_stale_backend(monkeypatch, killed):
    # First lsof finds pid 999; the follow-up poll shows the port released.
    monkeypatch.setattr(main_mod.subprocess, "run", _Run(["999", ""]))

    _free_stale_port(8080)

    assert killed == [(999, signal.SIGTERM)]


def test_escalates_to_sigkill_when_port_stays_held(monkeypatch, killed):
    # lsof keeps reporting pid 999 through every poll, so SIGTERM is ignored.
    monkeypatch.setattr(main_mod.subprocess, "run", _Run(["999"] * 40))

    _free_stale_port(8080)

    assert killed == [(999, signal.SIGTERM), (999, signal.SIGKILL)]


def test_spares_unrelated_process_on_our_port(monkeypatch, killed):
    monkeypatch.setattr(
        main_mod.subprocess, "run", _Run(["999", ""], ps_output="/usr/sbin/nginx -g daemon off;")
    )

    _free_stale_port(8080)

    assert killed == []


def test_never_targets_own_pid(monkeypatch, killed):
    monkeypatch.setattr(main_mod.subprocess, "run", _Run([str(os.getpid())]))

    _free_stale_port(8080)

    assert killed == []


def test_survives_missing_lsof(monkeypatch, killed):
    def _boom(argv, **kwargs):
        raise FileNotFoundError("lsof")

    monkeypatch.setattr(main_mod.subprocess, "run", _boom)

    _free_stale_port(8080)  # must not raise

    assert killed == []


def test_ignores_process_that_exits_before_sigterm(monkeypatch):
    monkeypatch.setattr(main_mod.os, "name", "posix")
    monkeypatch.setattr(main_mod.subprocess, "run", _Run(["999", ""]))

    def _gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(main_mod.os, "kill", _gone)

    _free_stale_port(8080)  # must not raise


# --- feature test: a real listener on a real port ---------------------------

HOLDER = textwrap.dedent(
    """
    import socket, sys, time
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", int(sys.argv[1])))
    s.listen(1)
    print("ready", flush=True)
    time.sleep(120)
    """
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_is_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only cleanup path")
@pytest.mark.skipif(
    subprocess.run(["which", "lsof"], capture_output=True).returncode != 0,
    reason="lsof not installed",
)
def test_frees_port_held_by_real_stale_backend(tmp_path):
    """End to end: a live process squatting the port is killed and the port reopens."""
    # The filename carries "trail_simulator" so the ps command-line guard matches.
    holder_py = tmp_path / "trail_simulator_holder.py"
    holder_py.write_text(HOLDER)
    port = _free_port()

    proc = subprocess.Popen(
        [sys.executable, str(holder_py), str(port)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert proc.stdout.readline().strip() == "ready"
        assert not _port_is_free(port), "holder should own the port"

        _free_stale_port(port)

        for _ in range(50):  # up to ~5s for the kernel to release the socket
            if _port_is_free(port):
                break
            time.sleep(0.1)
        assert _port_is_free(port), "stale listener was not cleared"
        assert proc.poll() is not None, "holder process should be dead"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
