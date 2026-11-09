"""The incident code catalogue (ADR-0048, OBS-07).

One backend-owned table: every incident carries one of these codes, and each
code (except ``unexpected``) has exactly one remedy line. Assign codes at the
raise site, never by parsing message text.
"""
from __future__ import annotations

from dataclasses import dataclass

FAULT = "fault"
REJECTION = "rejection"
CAP_TRIP = "cap_trip"
CLIENT_FAILURE = "client_failure"

KINDS = (FAULT, REJECTION, CAP_TRIP, CLIENT_FAILURE)

UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class CodeEntry:
    code: str
    kinds: tuple[str, ...]
    remedy: str | None


def _e(code: str, kinds: tuple[str, ...], remedy: str | None) -> CodeEntry:
    return CodeEntry(code, kinds, remedy)


_ENTRIES = [
    _e("route.no_route", (FAULT, REJECTION),
       "Move the pins onto connected walkable ground (same landmass, not water), "
       "then reset the pins and walk again."),
    _e("route.rejected", (FAULT, REJECTION),
       "The router rejected these points; check the pins are valid, reset them "
       "and try again."),
    _e("route.service_down", (FAULT, REJECTION),
       "The host could not get a route from the public OSRM router; your "
       "device's connection to the host is fine. Check the host's internet "
       "connection, or wait a minute if the router is busy, then walk again."),
    _e("device.tunnel_down", (FAULT,),
       "Start the tunnel on the host: `sudo pymobiledevice3 remote tunneld`. "
       "Auto-resume continues once the phone is reachable."),
    _e("device.not_reachable", (FAULT,),
       "Connect the iPhone by USB and tap Trust, or put it on the host's Wi-Fi "
       "with Wi-Fi connections enabled."),
    _e("device.multiple", (FAULT,),
       "Restart the backend with `--udid` for the phone you mean."),
    _e("device.connection_lost", (FAULT,),
       "Usually a Wi-Fi change; wait for auto-resume, or check the phone is on "
       "the host's network and the tunnel is running."),
    _e("device.adb", (FAULT,),
       "Check `adb devices` lists the phone, that it is rooted Android 12+, and "
       "that platform-tools is installed."),
    _e("session.auto_resume_failed", (FAULT,),
       "Read this incident's lead-up log for the cause, then Reset GPS and walk "
       "again."),
    _e("session.already_active", (REJECTION,),
       "Stop the current walk before starting a new one."),
    _e("session.not_active", (REJECTION,),
       "Start a walk first; this action needs a running or paused session."),
    _e("session.reset_while_active", (REJECTION,),
       "Stop the walk, then Reset GPS."),
    _e("safety.cooldown", (REJECTION,),
       "Wait out the cooldown shown, or start with the cooldown skipped if the "
       "jump is intended."),
    _e("safety.speed_cap", (CAP_TRIP,),
       "A position was skipped and the walk continues; repeated trips mean the "
       "route jumps, so check the route."),
    _e("safety.jump_cap", (CAP_TRIP,),
       "A position was skipped and the walk continues; repeated trips mean the "
       "route jumps, so check the route."),
    _e("addressing.no_devices", (REJECTION,),
       "Connect and pair the phone with the host (USB and Trust), and check the "
       "tunnel is running."),
    _e("addressing.client_unmatched", (REJECTION,),
       "In the Controller app's Settings, pick this phone in the Device list and "
       "save the client ID to bind it."),
    _e("addressing.device_held", (REJECTION,),
       "Another client holds this phone; use that client's ID, or Take over from "
       "the web UI's admin panel."),
    _e("addressing.unknown_device", (REJECTION,),
       "The saved device name no longer matches; pick a device from the "
       "backend's list again."),
    _e("addressing.ambiguous", (REJECTION,),
       "Several phones are connected; send a client ID (Controller app Settings) "
       "or choose a device in the web UI."),
    _e("binding.conflict", (REJECTION,),
       "That client ID or phone is already paired; choose another client ID, or "
       "have the operator take over."),
    _e("binding.unknown_device", (REJECTION,),
       "That phone is no longer connected; refresh the device list."),
    _e("follow.unknown_client", (REJECTION,),
       "That client is no longer bound; refresh the follow list."),
    _e("follow.self", (REJECTION,),
       "Pick a leader other than this phone."),
    _e("geocode.service_down", (REJECTION,),
       "The host cannot use the address search service (Nominatim); check its "
       "internet connection or search again later."),
    _e("request.invalid", (REJECTION,),
       "The client sent a value the backend refuses (see the detail), such as a "
       "speed above 20 km/h; usually a client bug."),
    _e("request.not_found", (REJECTION,),
       "The client called an endpoint this backend lacks; update the backend or "
       "the client so their versions match."),
    _e("client.unreachable", (CLIENT_FAILURE,),
       "If the host was down or asleep, keep it awake or restart the backend; if "
       "it was up, check the phone and host share a network and the backend URL "
       "in Settings."),
    _e("client.live_dropped", (CLIENT_FAILURE,),
       "The live connection dropped and came back; if this repeats, check Wi-Fi "
       "signal and whether the host sleeps."),
    _e("client.timeout", (CLIENT_FAILURE,),
       "The backend answered too slowly; check the host's load and the network."),
    _e("client.undecodable", (CLIENT_FAILURE,),
       "The app and backend versions probably differ; update both."),
    _e(UNEXPECTED, (FAULT, REJECTION), None),
]

CATALOGUE: dict[str, CodeEntry] = {e.code: e for e in _ENTRIES}


def remedy_for(code: str) -> str | None:
    entry = CATALOGUE.get(code)
    return entry.remedy if entry else None


def is_known(code: str) -> bool:
    return code in CATALOGUE


def is_client_code(code: str) -> bool:
    entry = CATALOGUE.get(code)
    return entry is not None and CLIENT_FAILURE in entry.kinds


def catalogue_payload() -> list[dict]:
    return [
        {"code": e.code, "kinds": list(e.kinds), "remedy": e.remedy}
        for e in _ENTRIES
    ]
