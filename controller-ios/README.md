# TrailController — Xcode Setup & Sideload Guide

TrailController is a sideloaded native iOS app that replaces the trail-simulator web UI. It gives you a native MapKit map with two-tap origin/destination pin selection, a breadcrumb trail, address search, Walk/Pause/Resume/Stop controls, a speed slider, cooldown handling, and a step-companions panel. It drives the trail-simulator backend over your LAN — HTTP for REST calls (`/api/*`) and one WebSocket (`/ws/live`) for live state. A free Apple ID is sufficient for sideloading.

The Xcode project already exists in this repo (`controller-ios/ControllerApp/`). This guide tells you how to open, sign, build, and sideload it — you do **not** create the project from scratch.

## 1. Open the Xcode project

1. Open Xcode (16 or later).
2. **File → Open…** → select `controller-ios/ControllerApp/ControllerApp.xcodeproj`.
3. Wait for Xcode to resolve the project. The source lives one level below the `.xcodeproj`, under `ControllerApp/ControllerApp/`:
   ```
   ControllerApp/ControllerApp/App/          # @main entry (ControllerAppApp.swift)
   ControllerApp/ControllerApp/Models/       # Codable request/response types
   ControllerApp/ControllerApp/Network/      # BackendClient (REST), LiveStatusSubscriber (WS), BackendConfig
   ControllerApp/ControllerApp/Store/        # SessionStore (state + breadcrumb)
   ControllerApp/ControllerApp/Views/        # MapScreen, SessionControls, SearchBar, SettingsScreen, StepCompanionsPanel, RootView
   ControllerApp/ControllerApp/Resources/    # Info.plist
   ControllerApp/ControllerApp/Assets.xcassets
   ```
   Tests live alongside in `ControllerApp/ControllerAppTests/`.

## 2. Signing

1. Click the top-level project in the navigator → select the **ControllerApp** target.
2. **Signing & Capabilities** tab → **Team** → pick your Apple ID (add one via Xcode → Settings → Accounts if needed).
3. Set a unique **Bundle Identifier**, e.g. `com.yourname.trailcontroller`. Apple requires it to be globally unique, so use your own reverse-domain prefix.
4. Ensure **Automatically manage signing** is checked.

## 3. Info.plist path (already configured)

The target's **Build Settings → Info.plist File** is set to `ControllerApp/Resources/Info.plist`. You don't need to change anything — this is noted only for troubleshooting. If the build fails with a missing-Info.plist error after moving files around, confirm that Build Setting still points at `ControllerApp/Resources/Info.plist`.

The bundled `Info.plist` already declares the keys the app needs:
- `NSLocationWhenInUseUsageDescription` — used only to center the map on you; coordinates are never sent to the backend.
- `NSLocalNetworkUsageDescription` — needed to reach the backend over your local Wi-Fi.
- `NSAppTransportSecurity → NSAllowsLocalNetworking` — allows the plain-HTTP LAN connection to the Mac.

## 4. Build

1. Pick any iOS Simulator (or your iPhone — see step 5) as the run destination.
2. Build with **⌘B**. To run the test suite, press **⌘U** (targets `ControllerAppTests`).

> **Note**: The project targets a recent iOS SDK (`IPHONEOS_DEPLOYMENT_TARGET = 26.0` in the Xcode project). Build with a matching Xcode/SDK, or lower the deployment target in **Build Settings** if you need to install on an older iOS version.

## 5. Sideload to a physical iPhone

1. Connect iPhone via USB. Trust the Mac on the phone if prompted.
2. Select your iPhone as the run destination in the toolbar.
3. Click **Run** (⌘R). Xcode builds and installs.
4. On the phone: **Settings → General → VPN & Device Management** → trust your developer certificate.
5. Open **TrailController** — it will ask for Location and Local Network permission. Grant both so the map can center on you and the app can reach the backend.

> **Note**: Free Apple ID sideloads expire after 7 days. Re-run from Xcode to refresh.

## 6. Connect to trail-simulator

1. On the Mac, start the backend bound to the LAN (run from the project root, see the top-level [`README.md`](../README.md)):
   ```bash
   uv run trail-simulator --host 0.0.0.0 --port 8787
   ```
   The default backend URL baked into the app is `http://127.0.0.1:8787`, which only works in the iOS Simulator on the same Mac. On a physical iPhone you must point the app at the Mac's LAN IP.
2. In TrailController, tap the **gear** icon (top right) → **Settings**.
3. In the **Backend** field, enter the Mac's address as a full URL, e.g. `http://192.168.1.50:8787` (use your Mac's actual LAN IP).
4. Tap **Test connection**. On success you'll see `OK — state: idle`. On failure you'll see `Failed: …` — check that the backend is running with `--host 0.0.0.0`, that both devices are on the same Wi-Fi, and that the IP/port are correct.
5. Tap **Save**. The app reconnects the `/ws/live` WebSocket to the new address and persists it for next launch.

## 7. Using the app

1. **Drop pins.** Tap the map once to drop the **Start** pin (green), then tap again to drop the **End** pin (red). A crosshair overlay shows until both pins are set. Alternatively, use the **search bar** at the top — type an address or place name, hit search, and tap a result to drop the next pin there.
2. **Pick a speed.** Drag the **Speed** slider (0.5–20 km/h; defaults to a 4 km/h walking pace).
3. **Walk.** Tap **Walk**. The button is enabled only once both pins are set and the session is idle. If the requested move is gated by the backend cooldown, an alert appears with the reason, jump distance, and required wait — you can dismiss it or tap **Skip cooldown**.
4. **Watch the route.** A blue dot marks the live position and a green breadcrumb polyline traces the path as the route plays. The breadcrumb only extends while the session is in an active state (`starting`, `running`, or `paused`) — it never splices in stale coordinates from a previous route.
5. **Pause / Resume / Stop.** **Pause** appears while running; **Resume** appears while paused; **Stop** appears in any active state (`starting`, `running`, `paused`, `reconnecting`).
6. **Reset.** Tap the **Reset pins** button (top-right of the map) to clear both pins and the breadcrumb so you can plan a fresh route.

### State pill

The pill in the top-left navigation bar reflects the live `SessionState` from the backend: `idle`, `starting`, `running`, `paused`, `stopping`, `reconnecting`, or `error` (an unrecognized value shows as `unknown`). It is color-coded — green for running, orange for paused, yellow for stopping/reconnecting, blue for starting, red for error.

### Step companions

The **Step companions** panel below the controls lists any `StepCompanion` apps currently connected to the backend (label, optional device UDID, and total acked steps), or "No step companions connected." when none are attached. See [`companion-ios/README.md`](../companion-ios/README.md) for the companion sideload guide.
