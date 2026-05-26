# Merge StepCompanion into ControllerApp — Design Spec

**Date:** 2026-05-26
**Status:** Proposed
**Approach:** A — absorb `companion-ios/StepCompanion` into the existing `controller-ios/ControllerApp` Xcode project

## 1. Goal

Ship one sideloaded iOS app that simultaneously:

1. Controls the trail-simulator backend (existing ControllerApp role: map, search, session controls, breadcrumb, speed slider).
2. Subscribes to backend step events and writes them to the local device's HealthKit (existing StepCompanion role).

The merged app runs on the **spoofed phone** — the same iPhone whose GPS the backend is driving. Backend (Mac) topology unchanged; the existing standalone StepCompanion project is retired once parity is verified.

## 2. Non-goals

- Replacing the backend or web UI.
- Supporting a "companion-only" or "controller-only" runtime mode. The merged app always exposes both surfaces.
- Multi-phone companion fanout from inside the app. The backend still supports multiple WS clients on `/ws/steps`, but the merged app contributes exactly one local writer.
- Computing steps client-side. The backend remains the source of truth.
- Renaming the product. Display name stays **TrailController**; bundle identifier unchanged.

## 3. High-level architecture

```
ControllerApp (single iOS target)
├── App/                       ControllerAppApp.swift — @main, starts BackgroundAudioKeeper, requests HK auth
├── Network/                   BackendClient (REST), LiveStatusSubscriber (/ws/live), BackendConfig
├── Health/                    [NEW] StepClient (/ws/steps), HealthWriter, BackgroundAudioKeeper, HealthStore
├── Store/                     SessionStore (+ health-state additions)
├── Models/                    + StepEvent
├── Views/
│   ├── RootView               TabView host: Map | Health | Settings
│   ├── MapTabView             [NEW] wraps existing map/search/controls/companions
│   ├── HealthTabView          [NEW] auth status, on/off switch, live + cumulative counters
│   ├── SettingsTabView        [NEW] wraps existing SettingsScreen contents
│   └── StepCompanionsPanel    repurposed to show "This Device" row (HK auth + live writes)
└── Resources/Info.plist       + UIBackgroundModes=[audio]
```

Two long-lived WebSocket subscribers run concurrently:

- `LiveStatusSubscriber` → `/ws/live` (existing — drives map, breadcrumb, controls).
- `StepClient` → `/ws/steps` (new — drives HealthKit writes).

Both reuse the same `BackendConfig.baseURL`. There is no second host/port input; the Health tab uses whatever the Settings tab is configured with.

## 4. Components

### 4.1 New files (ported from StepCompanion, lightly adapted)

| File | Source | Adaptations |
|---|---|---|
| `Health/StepClient.swift` | `companion-ios/.../StepClient.swift` | URL no longer derived from its own `@AppStorage` — caller passes a `URL` built from `BackendConfig`. `hello` payload `device_label` defaults to `UIDevice.current.name`. |
| `Health/HealthWriter.swift` | `companion-ios/.../HealthWriter.swift` | Unchanged. |
| `Health/BackgroundAudioKeeper.swift` | `companion-ios/.../BackgroundAudioKeeper.swift` | Unchanged. |
| `Models/StepEvent.swift` | inlined in `StepClient.swift` previously | Lifted to its own file for symmetry with other Models. |

### 4.2 New SwiftUI views

- **`HealthTabView`** — Form layout:
  - `Section("HealthKit")`: status row (granted / pending / unavailable / error) + "Request permission" button when not granted.
  - `Section("Step writing")`: `Toggle("Write steps to HealthKit", isOn: $healthEnabled)`. When off, `StepClient` is disconnected and incoming events ignored.
  - `Section("This session")`: live steps + distance written since toggle was last enabled.
  - `Section("Cumulative")`: total steps + distance written by the app, persisted in UserDefaults.
  - `Section("Errors")`: visible only if `client.lastError ?? writer.lastError != nil`.
- **`MapTabView`** — extracts the current `RootView` body (search + map + controls + companions panel) into its own view; no behavioral change.
- **`SettingsTabView`** — thin wrapper that pushes `SettingsScreen` content inside a `NavigationStack`. Removes the toolbar gear icon + sheet from the map.

### 4.3 Repurposed `StepCompanionsPanel`

Title → "This Device". Body renders a single row:

- HealthKit auth dot (green/red).
- "Writes enabled" / "Writes off" subtitle from the local toggle.
- Live step counter for current session (same number `HealthTabView` shows).

The backend-side `stepCompanions` list is no longer iterated; the panel reads from the local `HealthStore` (see 4.4) instead. The model field on `SessionStore.latest.stepCompanions` is left intact in `StatusSnapshot` for backward compatibility but no longer drives UI.

### 4.4 New `HealthStore` (state container)

```swift
@MainActor
final class HealthStore: ObservableObject {
    @Published var enabled: Bool           // user toggle, persisted
    @Published var sessionSteps: Int        // resets when toggle flips on
    @Published var sessionDistanceM: Double
    @Published var cumulativeSteps: Int     // persisted
    @Published var cumulativeDistanceM: Double
    let writer: HealthWriter
    let client: StepClient
    func setEnabled(_ on: Bool, baseURL: URL)  // connect/disconnect client
    func apply(event: StepEvent)               // called by client, updates counters, persists cumulative
}
```

Wiring:
- `ControllerAppApp` creates `HealthStore` (and `BackgroundAudioKeeper`) at launch, injects via `.environmentObject`.
- On first launch, `HealthWriter.requestAuthorization()` runs in `.task`. If granted and `enabled == true`, `StepClient.connect()` fires.
- `BackendConfig` change → `HealthStore` reconnects with the new URL (mirrors `LiveStatusSubscriber` behavior in `RootView`).

## 5. Data flow

```
Backend (Mac)
   │
   ├── /ws/live ──────────► LiveStatusSubscriber ──► SessionStore ──► MapTabView
   │
   └── /ws/steps ─────────► StepClient ──► HealthStore.apply(event)
                                              │
                                              ├──► HealthWriter.writeSteps()  → HealthKit
                                              └──► counters → HealthTabView, "This Device" row
```

## 6. UI / navigation

Root becomes a `TabView` with three tabs:

| Tab | Icon | Owner |
|---|---|---|
| Map | `map` | MapTabView (current RootView body, minus gear toolbar) |
| Health | `heart.text.square` | HealthTabView |
| Settings | `gearshape` | SettingsTabView |

State pill (Running / Paused / etc.) stays in the Map tab's nav bar. Settings sheet is replaced by the Settings tab; the gear toolbar item is removed.

## 7. Lifecycle & background

- `BackgroundAudioKeeper.start()` is called once in `ControllerAppApp.init()` (matching StepCompanion's pattern).
- `audio` background mode added to `ControllerApp/Resources/Info.plist`.
- HealthKit entitlement added to a new `ControllerApp/Resources/ControllerApp.entitlements` (or merged into the existing one if present).
- Both WebSocket tasks (`/ws/live`, `/ws/steps`) survive backgrounding because the audio session keeps the process alive.

## 8. Capabilities & Info.plist changes

`ControllerApp/Resources/Info.plist` additions:

```xml
<key>UIBackgroundModes</key>
<array><string>audio</string></array>
<key>NSHealthShareUsageDescription</key>
<string>This app reads HealthKit authorization status to show whether step writes are enabled.</string>
<key>NSHealthUpdateUsageDescription</key>
<string>This app writes step count and walking distance from trail-simulator sessions to HealthKit.</string>
```

Existing keys (`NSLocationWhenInUseUsageDescription`, `NSLocalNetworkUsageDescription`, `NSAppTransportSecurity → NSAllowsLocalNetworking`) remain.

Xcode target additions:
- **Capability: HealthKit** (adds `com.apple.developer.healthkit` to entitlements).
- **Linked framework:** `HealthKit.framework`, `AVFoundation.framework` (likely auto-linked but called out for the plan).

Bundle identifier and Team unchanged.

## 9. Persistence

`UserDefaults` keys (additive):

- `health.enabled` (Bool, default `true`) — local toggle.
- `health.cumulativeSteps` (Int, default `0`).
- `health.cumulativeDistanceM` (Double, default `0`).

The legacy StepCompanion keys (`hostText`, `portText`, `deviceLabel`, `deviceUDID`) are not used; the merged app derives host/port from `BackendConfig`.

## 10. Testing

New unit tests under `ControllerAppTests/`:

- `HealthStoreTests` — toggle flips connect/disconnect; `apply(event:)` increments session & cumulative counters; cumulative survives a `HealthStore` re-init (UserDefaults read-back).
- `StepEventDecodingTests` — decode happy path + ignore non-`steps` events + ignore zero-step events.
- `StepClientURLBuildingTests` — given a `BackendConfig`, produces `ws://host:port/ws/steps`.

`HealthWriter` is not unit-tested (HealthKit availability gates it on real device) — left to manual verification on a sideloaded build.

Existing tests (`BackendClientTests`, `LiveStatusSubscriberTests`, `SessionStoreTests`, `StatusSnapshotDecodingTests`) remain green; no expected changes.

## 11. Migration

1. Land the merged app behind no flag (additive code).
2. Verify on the sideloaded build: map control, /ws/live, /ws/steps, HealthKit writes, background survival.
3. Delete `companion-ios/` from the repo in a follow-up commit.
4. Update top-level `README.md` and `controller-ios/README.md` to mention HealthKit setup; delete `companion-ios/README.md`.

## 12. Risks & open questions

- **HealthKit entitlement on free Apple ID.** HealthKit requires a paid Apple Developer Program membership; free sideloads cannot enable it. If the user is on a free Apple ID, the merged app will fail to install. **Action:** confirm with user before implementation (resolve before plan executes).
- **Two WebSockets on one app.** Backend already supports this; no change needed. iOS allows it.
- **Background audio in App Store review.** Not relevant — app is sideloaded only.
- **`StepClient.hello` `udid` field** previously came from user input. Merged app sends an empty `udid` and a `device_label` of `UIDevice.current.name`. Backend treats `udid` as optional today.

## 13. Out of scope (future work, not in this spec)

- Removing the backend's `stepCompanions` broadcast list once no remote companions remain.
- Watch app companion.
- Per-session step history view (currently we only show session + cumulative).
