# iOS Controller App (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a sideloaded iOS app (`controller-ios/`) that replaces the Leaflet web UI as a controller for the existing FastAPI backend. Web UI is kept in parallel. No changes to backend in this phase.

**Architecture:** SwiftUI + MapKit app, iOS 17+ target. Talks to backend over HTTP (REST under `/api`) and one WebSocket (`/ws/live`) for status pushes. State held in a `@MainActor`-isolated `SessionStore` observable; network isolated in a `BackendClient` actor. Pure-Swift logic is TDD-covered; UI is verified manually on a physical device per a written protocol.

**Tech Stack:** Swift 5.10+, SwiftUI, MapKit, URLSession, URLSessionWebSocketTask, XCTest. No third-party dependencies.

**Repo location:** `controller-ios/` sibling to existing `companion-ios/`.

**Companion to spec:** `docs/superpowers/specs/2026-05-18-ios-controller-and-remote-spoofing-design.md`

> **⚠️ Post-scaffold path correction (added 2026-05-18 after Task 1):**
> Xcode created a nested project folder. Apply this transform to every path in this plan:
> - `controller-ios/ControllerApp/<subdir>/...` → `controller-ios/ControllerApp/ControllerApp/<subdir>/...`
> - `controller-ios/ControllerAppTests/...` → `controller-ios/ControllerApp/ControllerAppTests/...`
> - `controller-ios/ControllerApp.xcodeproj` → `controller-ios/ControllerApp/ControllerApp.xcodeproj`
> - `controller-ios/docs/...` unchanged
>
> `xcodebuild` commands should use `-project controller-ios/ControllerApp/ControllerApp.xcodeproj`. The scheme name remains `ControllerApp`. Info.plist already exists at the corrected location.

---

## API Contract (audited from backend on 2026-05-18)

All REST under `/api`; WebSocket at root. Base URL is `http://<host>:<port>` (default `http://127.0.0.1:8787`; LAN deployments use Mac's IP).

| Method | Path | Request | Success | Failure |
|---|---|---|---|---|
| GET | `/api/status` | — | `StatusSnapshot` (200) | — |
| POST | `/api/session` | `{start_lat, start_lon, destinations:[{lat,lon}], speed_kmh, loop?:bool, skip_cooldown?:bool}` | `{ok:true, reason:string}` (200) | 409 `{detail:string}` (already running) · 429 `{detail:{cooldown:true, required_wait_s, jump_km, reason}}` |
| POST | `/api/retarget` | `{destinations:[{lat,lon}], loop?:bool|null}` | `{ok:true}` | 409 · 502 `{detail:string}` |
| POST | `/api/speed` | `{speed_kmh}` (0 < x ≤ 20) | `{ok:true}` | 502 |
| POST | `/api/pause` | — | `{ok:true}` | — |
| POST | `/api/resume` | — | `{ok:true}` | — |
| POST | `/api/stop` | — | `{ok:true}` | — |
| GET | `/api/search?q=&limit=` (limit clamped 1..20) | — | `{results:[{display_name, lat, lon, type}]}` | 502 |

WebSocket `/ws/live`:
- Server pushes `StatusSnapshot` JSON on every state change; sends initial snapshot on accept.
- Max 64-deep server queue per client; oldest dropped on overflow. Client should expect latest-wins.

`StatusSnapshot` JSON shape:
```json
{
  "state": "idle|starting|running|paused|stopping|reconnecting|error",
  "session_id": 0|null,
  "current_lat": 0.0|null,
  "current_lon": 0.0|null,
  "target_lat": 0.0|null,
  "target_lon": 0.0|null,
  "speed_kmh": 0.0,
  "progress_m": 0.0,
  "total_m": 0.0,
  "last_error": "..."|null,
  "cooldown_remaining_s": 0.0,
  "steps_sent": 0,
  "step_companions": [
    {"label":"...","udid":"..."|null,"connected_at_iso":"...","last_heartbeat_iso":"...","total_acked":0}
  ]
}
```

---

## File Structure

The agent writes Swift sources into `controller-ios/ControllerApp/...`. The Xcode project (`ControllerApp.xcodeproj`) is scaffolded manually by the user per the README — same pattern as `companion-ios/StepCompanion/`. Once scaffolded, the user drags the source folders into the Xcode project navigator.

```
controller-ios/
├── README.md                                   ← Task 14
├── ControllerApp/
│   ├── App/
│   │   └── ControllerAppApp.swift             ← Task 11
│   ├── Models/
│   │   ├── SessionState.swift                 ← Task 3
│   │   ├── StatusSnapshot.swift               ← Task 3
│   │   ├── StepCompanionInfo.swift            ← Task 3
│   │   ├── Destination.swift                  ← Task 3
│   │   ├── SessionStartRequest.swift          ← Task 3
│   │   ├── RetargetRequest.swift              ← Task 3
│   │   ├── SpeedRequest.swift                 ← Task 3
│   │   ├── SearchResult.swift                 ← Task 3
│   │   ├── CooldownDetail.swift               ← Task 3
│   │   └── BackendError.swift                 ← Task 3
│   ├── Network/
│   │   ├── BackendConfig.swift                ← Task 4
│   │   ├── BackendClient.swift                ← Task 4
│   │   └── LiveStatusSubscriber.swift         ← Task 5
│   ├── Store/
│   │   └── SessionStore.swift                 ← Task 6
│   ├── Views/
│   │   ├── RootView.swift                     ← Task 11
│   │   ├── MapScreen.swift                    ← Task 7
│   │   ├── SearchBar.swift                    ← Task 8
│   │   ├── SessionControls.swift              ← Task 9
│   │   ├── StepCompanionsPanel.swift          ← Task 10
│   │   └── SettingsScreen.swift               ← Task 11
│   └── Resources/
│       └── Info.plist                          ← Task 1 (manual)
└── ControllerAppTests/
    ├── StatusSnapshotDecodingTests.swift      ← Task 3
    ├── BackendClientTests.swift               ← Task 4
    ├── LiveStatusSubscriberTests.swift        ← Task 5
    └── SessionStoreTests.swift                ← Task 6
```

**Sub-skill note (TDD scope):** Tasks 3–6 are TDD-covered (pure logic; XCTest in Xcode or via `xcodebuild test`). Tasks 7–11 are UI integration and verified manually on device in Task 12; no UI snapshot tests are introduced in this phase.

---

## Stage A — Foundation (Tasks 1–6, sequential)

### Task 1: Manual Xcode scaffold + Info.plist

**Files:**
- Create: `controller-ios/ControllerApp.xcodeproj` (via Xcode UI)
- Create: `controller-ios/ControllerApp/Resources/Info.plist`

This task is performed by the user, not an agent. Agents that reach this task should stop and report back; the user runs through Xcode UI per the README they'll write in Task 14. The agent can pre-create the on-disk `controller-ios/ControllerApp/` directory tree and an `Info.plist` skeleton so the user only has to do the Xcode steps.

- [ ] **Step 1: Create the on-disk directory layout**

Run:
```bash
cd /Users/jl26/habitDevs/trail-simulator
mkdir -p controller-ios/ControllerApp/{App,Models,Network,Store,Views,Resources}
mkdir -p controller-ios/ControllerAppTests
```

- [ ] **Step 2: Write Info.plist with the minimum keys this app needs**

Create `controller-ios/ControllerApp/Resources/Info.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>TrailController</string>
    <key>NSLocationWhenInUseUsageDescription</key>
    <string>This app uses your location only to center the map on you. Coordinates are never sent to the backend.</string>
    <key>NSLocalNetworkUsageDescription</key>
    <string>This app connects to the trail-simulator backend on your local Wi-Fi network.</string>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
    <key>UISupportedInterfaceOrientations</key>
    <array>
        <string>UIInterfaceOrientationPortrait</string>
    </array>
    <key>UILaunchScreen</key>
    <dict/>
</dict>
</plist>
```

- [ ] **Step 3: Stop and request user to scaffold Xcode project**

Report to the user (or orchestrating agent):

> Directory tree and Info.plist created at `controller-ios/`. Please scaffold the Xcode project manually:
> 1. Xcode → File → New → Project → iOS → App
> 2. Product Name: `ControllerApp`; Bundle Id: e.g. `com.<you>.trailcontroller`; Interface: SwiftUI; Language: Swift; deployment target: **iOS 17.0**
> 3. Save location: `controller-ios/` (Xcode will create `controller-ios/ControllerApp.xcodeproj`)
> 4. Delete the placeholder `ContentView.swift` and `ControllerAppApp.swift` Xcode generated; subsequent tasks will write replacements into `controller-ios/ControllerApp/`
> 5. Right-click the `ControllerApp` group → Add Files → select the `App/`, `Models/`, `Network/`, `Store/`, `Views/`, `Resources/` folders inside `controller-ios/ControllerApp/`; check "Create groups", uncheck "Copy items if needed"
> 6. Build Settings → search "Info.plist" → set **Info.plist File** to `ControllerApp/Resources/Info.plist`
> 7. Signing & Capabilities → set your Team and Bundle Id
> 8. Create a `ControllerAppTests` test target if Xcode didn't, pointing at `controller-ios/ControllerAppTests/`

- [ ] **Step 4: No commit yet — Xcode pbxproj contains absolute paths and signing IDs the user picks**

The user commits the `.xcodeproj` after their scaffold pass.

---

### Task 2: Backend contract reference doc

**Files:**
- Create: `controller-ios/docs/api-contract.md`

This is a checked-in copy of the API contract section from this plan, so the controller-ios app has a self-contained reference and future API changes are visible in `controller-ios/` diffs.

- [ ] **Step 1: Write `controller-ios/docs/api-contract.md`**

Copy the full "API Contract (audited from backend on 2026-05-18)" section from this plan verbatim into the new file. Add a one-line header: `# Backend HTTP + WebSocket Contract` and a one-line footer: `Source: trail_simulator/api/rest.py, ws.py, geocode.py — audited 2026-05-18.`

- [ ] **Step 2: Commit**

```bash
git add controller-ios/docs/api-contract.md
git commit -m "docs(controller-ios): add backend API contract reference"
```

---

### Task 3: Codable models + decode tests

**Files:**
- Create: `controller-ios/ControllerApp/Models/SessionState.swift`
- Create: `controller-ios/ControllerApp/Models/StatusSnapshot.swift`
- Create: `controller-ios/ControllerApp/Models/StepCompanionInfo.swift`
- Create: `controller-ios/ControllerApp/Models/Destination.swift`
- Create: `controller-ios/ControllerApp/Models/SessionStartRequest.swift`
- Create: `controller-ios/ControllerApp/Models/RetargetRequest.swift`
- Create: `controller-ios/ControllerApp/Models/SpeedRequest.swift`
- Create: `controller-ios/ControllerApp/Models/SearchResult.swift`
- Create: `controller-ios/ControllerApp/Models/CooldownDetail.swift`
- Create: `controller-ios/ControllerApp/Models/BackendError.swift`
- Test: `controller-ios/ControllerAppTests/StatusSnapshotDecodingTests.swift`

- [ ] **Step 1: Write failing tests for StatusSnapshot decoding**

Create `controller-ios/ControllerAppTests/StatusSnapshotDecodingTests.swift`:

```swift
import XCTest
@testable import ControllerApp

final class StatusSnapshotDecodingTests: XCTestCase {
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    func testDecodesIdleSnapshot() throws {
        let json = """
        {
          "state": "idle",
          "session_id": null,
          "current_lat": null,
          "current_lon": null,
          "target_lat": null,
          "target_lon": null,
          "speed_kmh": 0.0,
          "progress_m": 0.0,
          "total_m": 0.0,
          "last_error": null,
          "cooldown_remaining_s": 0.0,
          "steps_sent": 0,
          "step_companions": []
        }
        """.data(using: .utf8)!

        let snap = try decoder.decode(StatusSnapshot.self, from: json)
        XCTAssertEqual(snap.state, .idle)
        XCTAssertNil(snap.sessionId)
        XCTAssertEqual(snap.speedKmh, 0.0)
        XCTAssertTrue(snap.stepCompanions.isEmpty)
    }

    func testDecodesRunningSnapshotWithCompanion() throws {
        let json = """
        {
          "state": "running",
          "session_id": 42,
          "current_lat": 35.6700,
          "current_lon": 139.7000,
          "target_lat": 35.6800,
          "target_lon": 139.7100,
          "speed_kmh": 4.5,
          "progress_m": 120.0,
          "total_m": 980.0,
          "last_error": null,
          "cooldown_remaining_s": 0.0,
          "steps_sent": 153,
          "step_companions": [
            {"label":"iPhone","udid":"abc","connected_at_iso":"2026-05-18T12:00:00Z","last_heartbeat_iso":"2026-05-18T12:01:00Z","total_acked":153}
          ]
        }
        """.data(using: .utf8)!

        let snap = try decoder.decode(StatusSnapshot.self, from: json)
        XCTAssertEqual(snap.state, .running)
        XCTAssertEqual(snap.sessionId, 42)
        XCTAssertEqual(snap.stepCompanions.first?.label, "iPhone")
        XCTAssertEqual(snap.stepCompanions.first?.totalAcked, 153)
    }

    func testDecodesUnknownStateAsError() throws {
        // Forward-compat: backend may add states in the future.
        let json = """
        {
          "state": "future-state-we-dont-know",
          "session_id": null, "current_lat": null, "current_lon": null,
          "target_lat": null, "target_lon": null,
          "speed_kmh": 0.0, "progress_m": 0.0, "total_m": 0.0,
          "last_error": null, "cooldown_remaining_s": 0.0,
          "steps_sent": 0, "step_companions": []
        }
        """.data(using: .utf8)!
        let snap = try decoder.decode(StatusSnapshot.self, from: json)
        XCTAssertEqual(snap.state, .unknown)
    }
}
```

- [ ] **Step 2: Run the test, confirm it fails (types not defined)**

Run in Xcode (Cmd-U) or shell:
```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -30
```
Expected: build failure with "Cannot find type 'StatusSnapshot' in scope".

- [ ] **Step 3: Implement SessionState**

Create `controller-ios/ControllerApp/Models/SessionState.swift`:

```swift
import Foundation

enum SessionState: String, Codable, Equatable {
    case idle, starting, running, paused, stopping, reconnecting, error
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = SessionState(rawValue: raw) ?? .unknown
    }
}
```

- [ ] **Step 4: Implement StatusSnapshot + StepCompanionInfo**

Create `controller-ios/ControllerApp/Models/StepCompanionInfo.swift`:

```swift
import Foundation

struct StepCompanionInfo: Codable, Equatable, Identifiable {
    let label: String
    let udid: String?
    let connectedAtIso: String
    let lastHeartbeatIso: String
    let totalAcked: Int

    var id: String { udid ?? label }
}
```

Create `controller-ios/ControllerApp/Models/StatusSnapshot.swift`:

```swift
import Foundation

struct StatusSnapshot: Codable, Equatable {
    let state: SessionState
    let sessionId: Int?
    let currentLat: Double?
    let currentLon: Double?
    let targetLat: Double?
    let targetLon: Double?
    let speedKmh: Double
    let progressM: Double
    let totalM: Double
    let lastError: String?
    let cooldownRemainingS: Double
    let stepsSent: Int
    let stepCompanions: [StepCompanionInfo]
}
```

- [ ] **Step 5: Implement request models**

Create `controller-ios/ControllerApp/Models/Destination.swift`:

```swift
import Foundation

struct Destination: Codable, Equatable {
    let lat: Double
    let lon: Double
}
```

Create `controller-ios/ControllerApp/Models/SessionStartRequest.swift`:

```swift
import Foundation

struct SessionStartRequest: Codable, Equatable {
    let startLat: Double
    let startLon: Double
    let destinations: [Destination]
    let speedKmh: Double
    let loop: Bool
    let skipCooldown: Bool

    enum CodingKeys: String, CodingKey {
        case startLat = "start_lat"
        case startLon = "start_lon"
        case destinations
        case speedKmh = "speed_kmh"
        case loop
        case skipCooldown = "skip_cooldown"
    }
}
```

Create `controller-ios/ControllerApp/Models/RetargetRequest.swift`:

```swift
import Foundation

struct RetargetRequest: Codable, Equatable {
    let destinations: [Destination]
    let loop: Bool?
}
```

Create `controller-ios/ControllerApp/Models/SpeedRequest.swift`:

```swift
import Foundation

struct SpeedRequest: Codable, Equatable {
    let speedKmh: Double

    enum CodingKeys: String, CodingKey {
        case speedKmh = "speed_kmh"
    }
}
```

Create `controller-ios/ControllerApp/Models/SearchResult.swift`:

```swift
import Foundation

struct SearchResult: Codable, Equatable, Identifiable {
    let displayName: String
    let lat: Double
    let lon: Double
    let type: String

    var id: String { "\(lat),\(lon),\(displayName)" }
}

struct SearchResponse: Codable, Equatable {
    let results: [SearchResult]
}
```

- [ ] **Step 6: Implement CooldownDetail + BackendError**

Create `controller-ios/ControllerApp/Models/CooldownDetail.swift`:

```swift
import Foundation

struct CooldownDetail: Codable, Equatable {
    let cooldown: Bool
    let requiredWaitS: Double
    let jumpKm: Double
    let reason: String

    enum CodingKeys: String, CodingKey {
        case cooldown
        case requiredWaitS = "required_wait_s"
        case jumpKm = "jump_km"
        case reason
    }
}
```

Create `controller-ios/ControllerApp/Models/BackendError.swift`:

```swift
import Foundation

enum BackendError: Error, Equatable {
    case transport(String)             // URLSession failures, decode failures
    case sessionAlreadyActive(String)  // 409 from /api/session
    case sessionNotActive(String)      // 409 from /api/retarget
    case cooldown(CooldownDetail)      // 429 from /api/session
    case routing(String)               // 502 from /api/retarget or /api/speed
    case server(Int, String)           // any other non-2xx with detail
}
```

- [ ] **Step 7: Run tests, confirm they pass**

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10
```
Expected: `Test Suite 'StatusSnapshotDecodingTests' passed`.

- [ ] **Step 8: Commit**

```bash
git add controller-ios/ControllerApp/Models/ controller-ios/ControllerAppTests/StatusSnapshotDecodingTests.swift
git commit -m "feat(controller-ios): add Codable models for backend contract"
```

---

### Task 4: BackendClient (HTTP) + tests

**Files:**
- Create: `controller-ios/ControllerApp/Network/BackendConfig.swift`
- Create: `controller-ios/ControllerApp/Network/BackendClient.swift`
- Test: `controller-ios/ControllerAppTests/BackendClientTests.swift`

The client is an `actor` so concurrent calls from the SwiftUI layer serialize per-instance; URLSession itself is thread-safe but the actor protects the `baseURL` mutation when the user changes it in Settings.

- [ ] **Step 1: Write failing tests for BackendClient happy + error paths**

Create `controller-ios/ControllerAppTests/BackendClientTests.swift`:

```swift
import XCTest
@testable import ControllerApp

final class BackendClientTests: XCTestCase {

    // URLProtocol stub so tests run without a real backend.
    final class StubURLProtocol: URLProtocol {
        static var handler: ((URLRequest) -> (HTTPURLResponse, Data))?
        override class func canInit(with request: URLRequest) -> Bool { true }
        override class func canonicalRequest(for r: URLRequest) -> URLRequest { r }
        override func startLoading() {
            guard let h = Self.handler else { return }
            let (resp, data) = h(request)
            client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }
        override func stopLoading() {}
    }

    private func makeClient(_ handler: @escaping (URLRequest) -> (HTTPURLResponse, Data)) -> BackendClient {
        StubURLProtocol.handler = handler
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        let session = URLSession(configuration: config)
        return BackendClient(baseURL: URL(string: "http://stub.local")!, session: session)
    }

    func testFetchStatusDecodesSnapshot() async throws {
        let json = #"{"state":"idle","session_id":null,"current_lat":null,"current_lon":null,"target_lat":null,"target_lon":null,"speed_kmh":0,"progress_m":0,"total_m":0,"last_error":null,"cooldown_remaining_s":0,"steps_sent":0,"step_companions":[]}"#.data(using: .utf8)!
        let client = makeClient { req in
            XCTAssertEqual(req.url?.path, "/api/status")
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, json)
        }
        let snap = try await client.fetchStatus()
        XCTAssertEqual(snap.state, .idle)
    }

    func testStartSessionMaps409ToSessionAlreadyActive() async {
        let body = #"{"detail":"session already active"}"#.data(using: .utf8)!
        let client = makeClient { req in
            (HTTPURLResponse(url: req.url!, statusCode: 409, httpVersion: nil, headerFields: nil)!, body)
        }
        let req = SessionStartRequest(startLat: 0, startLon: 0, destinations: [.init(lat: 1, lon: 1)], speedKmh: 4, loop: false, skipCooldown: false)
        do {
            _ = try await client.startSession(req)
            XCTFail("expected throw")
        } catch let error as BackendError {
            if case .sessionAlreadyActive(let msg) = error {
                XCTAssertEqual(msg, "session already active")
            } else { XCTFail("wrong case: \(error)") }
        } catch { XCTFail("wrong error type: \(error)") }
    }

    func testStartSessionMaps429ToCooldown() async {
        let body = #"{"detail":{"cooldown":true,"required_wait_s":3600,"jump_km":50,"reason":"long jump"}}"#.data(using: .utf8)!
        let client = makeClient { req in
            (HTTPURLResponse(url: req.url!, statusCode: 429, httpVersion: nil, headerFields: nil)!, body)
        }
        let req = SessionStartRequest(startLat: 0, startLon: 0, destinations: [.init(lat: 1, lon: 1)], speedKmh: 4, loop: false, skipCooldown: false)
        do {
            _ = try await client.startSession(req)
            XCTFail("expected throw")
        } catch BackendError.cooldown(let detail) {
            XCTAssertEqual(detail.requiredWaitS, 3600)
            XCTAssertEqual(detail.reason, "long jump")
        } catch { XCTFail("wrong error: \(error)") }
    }

    func testSearchEncodesQuery() async throws {
        let body = #"{"results":[{"display_name":"Tokyo, Japan","lat":35.68,"lon":139.69,"type":"city"}]}"#.data(using: .utf8)!
        let client = makeClient { req in
            XCTAssertEqual(req.url?.path, "/api/search")
            XCTAssertTrue(req.url?.query?.contains("q=Tokyo") ?? false)
            return (HTTPURLResponse(url: req.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, body)
        }
        let res = try await client.search(query: "Tokyo")
        XCTAssertEqual(res.first?.displayName, "Tokyo, Japan")
    }
}
```

- [ ] **Step 2: Run, confirm failure**

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -20
```
Expected: build failure (`BackendClient` not defined).

- [ ] **Step 3: Implement BackendConfig**

Create `controller-ios/ControllerApp/Network/BackendConfig.swift`:

```swift
import Foundation

struct BackendConfig: Equatable {
    var baseURL: URL

    static let `default` = BackendConfig(baseURL: URL(string: "http://127.0.0.1:8787")!)

    static let storageKey = "BackendConfig.baseURL"

    static func loadFromUserDefaults(_ defaults: UserDefaults = .standard) -> BackendConfig {
        guard
            let raw = defaults.string(forKey: storageKey),
            let url = URL(string: raw)
        else { return .default }
        return BackendConfig(baseURL: url)
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(baseURL.absoluteString, forKey: Self.storageKey)
    }
}
```

- [ ] **Step 4: Implement BackendClient**

Create `controller-ios/ControllerApp/Network/BackendClient.swift`:

```swift
import Foundation

actor BackendClient {
    private var baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
        self.decoder = JSONDecoder()
        self.decoder.keyDecodingStrategy = .convertFromSnakeCase
        self.encoder = JSONEncoder()
        // Request bodies use explicit CodingKeys; no global key strategy.
    }

    func updateBaseURL(_ url: URL) {
        baseURL = url
    }

    func fetchStatus() async throws -> StatusSnapshot {
        try await getJSON("/api/status", as: StatusSnapshot.self)
    }

    @discardableResult
    func startSession(_ req: SessionStartRequest) async throws -> String {
        try await postJSON("/api/session", body: req, decode: OkReason.self).reason
    }

    @discardableResult
    func retarget(_ req: RetargetRequest) async throws -> Bool {
        try await postJSON("/api/retarget", body: req, decode: Ok.self).ok
    }

    @discardableResult
    func setSpeed(_ kmh: Double) async throws -> Bool {
        try await postJSON("/api/speed", body: SpeedRequest(speedKmh: kmh), decode: Ok.self).ok
    }

    func pause() async throws { _ = try await postEmpty("/api/pause") }
    func resume() async throws { _ = try await postEmpty("/api/resume") }
    func stop() async throws { _ = try await postEmpty("/api/stop") }

    func search(query: String, limit: Int = 8) async throws -> [SearchResult] {
        var comps = URLComponents(url: baseURL.appendingPathComponent("api/search"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        let req = URLRequest(url: comps.url!)
        let (data, response) = try await session.data(for: req)
        try checkOk(response, data: data, isStart: false)
        return try decoder.decode(SearchResponse.self, from: data).results
    }

    // MARK: - private

    private struct Ok: Codable { let ok: Bool }
    private struct OkReason: Codable { let ok: Bool; let reason: String }

    private func getJSON<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
        let url = baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        let (data, resp) = try await session.data(for: URLRequest(url: url))
        try checkOk(resp, data: data, isStart: false)
        return try decoder.decode(T.self, from: data)
    }

    private func postJSON<Body: Encodable, T: Decodable>(_ path: String, body: Body, decode: T.Type) async throws -> T {
        var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(body)
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: path.hasSuffix("/session"))
        return try decoder.decode(T.self, from: data)
    }

    private func postEmpty(_ path: String) async throws -> Bool {
        var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        req.httpMethod = "POST"
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: false)
        return (try? decoder.decode(Ok.self, from: data).ok) ?? true
    }

    private func checkOk(_ response: URLResponse, data: Data, isStart: Bool) throws {
        guard let http = response as? HTTPURLResponse else {
            throw BackendError.transport("non-HTTP response")
        }
        if (200..<300).contains(http.statusCode) { return }

        // Try to decode the FastAPI {"detail": ...} envelope.
        let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]

        switch http.statusCode {
        case 409:
            let msg = (detail as? String) ?? "conflict"
            throw isStart ? BackendError.sessionAlreadyActive(msg) : .sessionNotActive(msg)
        case 429:
            if let obj = detail as? [String: Any],
               let cooldownData = try? JSONSerialization.data(withJSONObject: obj),
               let cd = try? decoder.decode(CooldownDetail.self, from: cooldownData) {
                throw BackendError.cooldown(cd)
            }
            throw BackendError.server(429, String(describing: detail))
        case 502:
            throw BackendError.routing(detail as? String ?? "routing error")
        default:
            throw BackendError.server(http.statusCode, String(describing: detail))
        }
    }
}
```

- [ ] **Step 5: Run, confirm tests pass**

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10
```
Expected: `Test Suite 'BackendClientTests' passed`.

- [ ] **Step 6: Commit**

```bash
git add controller-ios/ControllerApp/Network/BackendConfig.swift \
        controller-ios/ControllerApp/Network/BackendClient.swift \
        controller-ios/ControllerAppTests/BackendClientTests.swift
git commit -m "feat(controller-ios): add BackendClient REST actor"
```

---

### Task 5: LiveStatusSubscriber (WebSocket) + tests

**Files:**
- Create: `controller-ios/ControllerApp/Network/LiveStatusSubscriber.swift`
- Test: `controller-ios/ControllerAppTests/LiveStatusSubscriberTests.swift`

The subscriber owns a `URLSessionWebSocketTask`, decodes incoming text frames into `StatusSnapshot`, and exposes an `AsyncStream<StatusSnapshot>` for the store to consume. Auto-reconnects with backoff (1s, 2s, 4s, cap 10s) until cancelled.

- [ ] **Step 1: Write failing test exercising the decode path**

Create `controller-ios/ControllerAppTests/LiveStatusSubscriberTests.swift`:

```swift
import XCTest
@testable import ControllerApp

final class LiveStatusSubscriberTests: XCTestCase {
    func testDecodeFrameProducesSnapshot() throws {
        let frame = #"{"state":"running","session_id":1,"current_lat":35.0,"current_lon":139.0,"target_lat":35.1,"target_lon":139.1,"speed_kmh":4,"progress_m":10,"total_m":100,"last_error":null,"cooldown_remaining_s":0,"steps_sent":5,"step_companions":[]}"#
        let snap = try LiveStatusSubscriber.decodeFrame(frame)
        XCTAssertEqual(snap.state, .running)
        XCTAssertEqual(snap.sessionId, 1)
    }

    func testDecodeRejectsGarbage() {
        XCTAssertThrowsError(try LiveStatusSubscriber.decodeFrame("not json"))
    }

    func testWebSocketURLBuildsCorrectly() {
        let http = URL(string: "http://192.168.1.5:8787")!
        XCTAssertEqual(LiveStatusSubscriber.webSocketURL(from: http).absoluteString, "ws://192.168.1.5:8787/ws/live")

        let https = URL(string: "https://example.com")!
        XCTAssertEqual(LiveStatusSubscriber.webSocketURL(from: https).absoluteString, "wss://example.com/ws/live")
    }
}
```

- [ ] **Step 2: Run, confirm failure**

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10
```
Expected: `LiveStatusSubscriber` not defined.

- [ ] **Step 3: Implement LiveStatusSubscriber**

Create `controller-ios/ControllerApp/Network/LiveStatusSubscriber.swift`:

```swift
import Foundation

/// Subscribes to `/ws/live` and yields `StatusSnapshot` updates as an AsyncStream.
/// Reconnects on transport errors with capped exponential backoff until cancelled.
actor LiveStatusSubscriber {
    private var task: URLSessionWebSocketTask?
    private var continuation: AsyncStream<StatusSnapshot>.Continuation?
    private var consumerTask: Task<Void, Never>?

    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    /// Starts the subscription. Calling again replaces the existing one.
    func start(baseURL: URL) -> AsyncStream<StatusSnapshot> {
        cancel()

        let wsURL = Self.webSocketURL(from: baseURL)
        let (stream, cont) = AsyncStream<StatusSnapshot>.makeStream()
        continuation = cont

        consumerTask = Task { [session, weak self] in
            var backoff: UInt64 = 1_000_000_000 // 1s in ns
            let cap: UInt64    = 10_000_000_000 // 10s

            while !Task.isCancelled {
                let task = session.webSocketTask(with: wsURL)
                await self?.setTask(task)
                task.resume()

                do {
                    while !Task.isCancelled {
                        let msg = try await task.receive()
                        switch msg {
                        case .string(let text):
                            if let snap = try? Self.decodeFrame(text) {
                                cont.yield(snap)
                            }
                        case .data(let data):
                            if let text = String(data: data, encoding: .utf8),
                               let snap = try? Self.decodeFrame(text) {
                                cont.yield(snap)
                            }
                        @unknown default:
                            break
                        }
                    }
                } catch {
                    // fall through to backoff
                }

                task.cancel(with: .normalClosure, reason: nil)
                if Task.isCancelled { break }

                try? await Task.sleep(nanoseconds: backoff)
                backoff = min(backoff * 2, cap)
            }
            cont.finish()
        }

        return stream
    }

    func cancel() {
        consumerTask?.cancel()
        consumerTask = nil
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        continuation?.finish()
        continuation = nil
    }

    private func setTask(_ t: URLSessionWebSocketTask) {
        task = t
    }

    /// Static helpers — kept static so they're testable without spinning up a real task.
    static func decodeFrame(_ text: String) throws -> StatusSnapshot {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let data = text.data(using: .utf8) else {
            throw BackendError.transport("non-utf8 frame")
        }
        return try decoder.decode(StatusSnapshot.self, from: data)
    }

    static func webSocketURL(from baseURL: URL) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        components.scheme = (baseURL.scheme == "https") ? "wss" : "ws"
        components.path = "/ws/live"
        components.query = nil
        return components.url!
    }
}
```

- [ ] **Step 4: Run, confirm tests pass**

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10
```
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add controller-ios/ControllerApp/Network/LiveStatusSubscriber.swift \
        controller-ios/ControllerAppTests/LiveStatusSubscriberTests.swift
git commit -m "feat(controller-ios): add WebSocket subscriber with auto-reconnect"
```

---

### Task 6: SessionStore (state + breadcrumb gating) + tests

**Files:**
- Create: `controller-ios/ControllerApp/Store/SessionStore.swift`
- Test: `controller-ios/ControllerAppTests/SessionStoreTests.swift`

`SessionStore` is `@MainActor`, `ObservableObject`, owns the latest `StatusSnapshot`, the breadcrumb trail (gated on active states — replicates the May 13 web-UI fix), and the pin-selection workflow. It calls `BackendClient` for actions and consumes the `LiveStatusSubscriber` stream.

**Critical invariant (replicates `frontend/static/app.js` May-13 fix):** Position pushes to the breadcrumb array happen **only** when `state ∈ {starting, running, paused}`. Snapshots in `idle/stopping/error/reconnecting` may carry stale coordinates from the previous route and must not pollute the trail. `clearBreadcrumb()` runs on each new Walk press.

- [ ] **Step 1: Write failing tests covering state, breadcrumb gating, and pin workflow**

Create `controller-ios/ControllerAppTests/SessionStoreTests.swift`:

```swift
import XCTest
import CoreLocation
@testable import ControllerApp

@MainActor
final class SessionStoreTests: XCTestCase {

    func snapshot(state: SessionState, lat: Double? = nil, lon: Double? = nil) -> StatusSnapshot {
        StatusSnapshot(state: state, sessionId: nil,
                       currentLat: lat, currentLon: lon,
                       targetLat: nil, targetLon: nil,
                       speedKmh: 0, progressM: 0, totalM: 0,
                       lastError: nil, cooldownRemainingS: 0,
                       stepsSent: 0, stepCompanions: [])
    }

    func testBreadcrumbAccumulatesOnlyInActiveStates() {
        let store = SessionStore()

        store.apply(snapshot: snapshot(state: .running, lat: 1, lon: 1))
        store.apply(snapshot: snapshot(state: .running, lat: 2, lon: 2))
        store.apply(snapshot: snapshot(state: .paused,  lat: 3, lon: 3))
        XCTAssertEqual(store.breadcrumb.count, 3)

        // Stale position in idle must not accumulate.
        store.apply(snapshot: snapshot(state: .idle,        lat: 99, lon: 99))
        store.apply(snapshot: snapshot(state: .stopping,    lat: 99, lon: 99))
        store.apply(snapshot: snapshot(state: .error,       lat: 99, lon: 99))
        store.apply(snapshot: snapshot(state: .reconnecting,lat: 99, lon: 99))
        XCTAssertEqual(store.breadcrumb.count, 3)

        // currentPosition still updates regardless of state so the marker tracks.
        XCTAssertEqual(store.currentPosition?.latitude, 99)
    }

    func testStartingState_includedInBreadcrumb() {
        let store = SessionStore()
        store.apply(snapshot: snapshot(state: .starting, lat: 1, lon: 1))
        XCTAssertEqual(store.breadcrumb.count, 1)
    }

    func testClearBreadcrumbResetsTrail() {
        let store = SessionStore()
        store.apply(snapshot: snapshot(state: .running, lat: 1, lon: 1))
        store.clearBreadcrumb()
        XCTAssertEqual(store.breadcrumb.count, 0)
    }

    func testPinSelectionRequiresOriginThenDestination() {
        let store = SessionStore()
        XCTAssertEqual(store.pinSelectionStage, .origin)
        store.setPin(at: CLLocationCoordinate2D(latitude: 1, longitude: 1))
        XCTAssertNotNil(store.origin)
        XCTAssertEqual(store.pinSelectionStage, .destination)
        store.setPin(at: CLLocationCoordinate2D(latitude: 2, longitude: 2))
        XCTAssertNotNil(store.destination)
        XCTAssertEqual(store.pinSelectionStage, .ready)
    }

    func testResetPinsClearsBoth() {
        let store = SessionStore()
        store.setPin(at: CLLocationCoordinate2D(latitude: 1, longitude: 1))
        store.setPin(at: CLLocationCoordinate2D(latitude: 2, longitude: 2))
        store.resetPins()
        XCTAssertNil(store.origin)
        XCTAssertNil(store.destination)
        XCTAssertEqual(store.pinSelectionStage, .origin)
    }
}
```

- [ ] **Step 2: Run, confirm failure**

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10
```
Expected: `SessionStore` not defined.

- [ ] **Step 3: Implement SessionStore**

Create `controller-ios/ControllerApp/Store/SessionStore.swift`:

```swift
import Foundation
import CoreLocation
import Combine

@MainActor
final class SessionStore: ObservableObject {

    enum PinStage: Equatable { case origin, destination, ready }

    @Published private(set) var latest: StatusSnapshot? = nil
    @Published private(set) var breadcrumb: [CLLocationCoordinate2D] = []
    @Published private(set) var currentPosition: CLLocationCoordinate2D? = nil
    @Published var origin: CLLocationCoordinate2D? = nil
    @Published var destination: CLLocationCoordinate2D? = nil
    @Published var speedKmh: Double = 4.0   // default walking pace
    @Published var lastError: BackendError? = nil

    var pinSelectionStage: PinStage {
        if origin == nil { return .origin }
        if destination == nil { return .destination }
        return .ready
    }

    var state: SessionState { latest?.state ?? .idle }

    // Active states gate breadcrumb accumulation — replicates the May 13
    // web-UI fix where idle/stopping/error/reconnecting carried stale
    // coordinates from the previous route and would otherwise splice into
    // the new trail.
    static let activeStates: Set<SessionState> = [.starting, .running, .paused]

    func apply(snapshot: StatusSnapshot) {
        latest = snapshot

        if let lat = snapshot.currentLat, let lon = snapshot.currentLon {
            let coord = CLLocationCoordinate2D(latitude: lat, longitude: lon)
            currentPosition = coord
            if Self.activeStates.contains(snapshot.state) {
                breadcrumb.append(coord)
            }
        }
    }

    func clearBreadcrumb() {
        breadcrumb.removeAll()
    }

    func setPin(at coord: CLLocationCoordinate2D) {
        switch pinSelectionStage {
        case .origin:       origin = coord
        case .destination:  destination = coord
        case .ready:        break
        }
    }

    func resetPins() {
        origin = nil
        destination = nil
    }
}
```

- [ ] **Step 4: Run, confirm tests pass**

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10
```
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add controller-ios/ControllerApp/Store/SessionStore.swift \
        controller-ios/ControllerAppTests/SessionStoreTests.swift
git commit -m "feat(controller-ios): add SessionStore with breadcrumb gating"
```

---

## Stage B — UI Components (Tasks 7–11, parallelizable after Stage A)

Stage B tasks depend only on Stage A artifacts. They can be dispatched to multiple subagents in parallel because they touch disjoint files.

### Task 7: MapScreen with two-tap pin selection

**Files:**
- Create: `controller-ios/ControllerApp/Views/MapScreen.swift`

- [ ] **Step 1: Implement MapScreen**

Create `controller-ios/ControllerApp/Views/MapScreen.swift`:

```swift
import SwiftUI
import MapKit
import CoreLocation

struct MapScreen: View {
    @EnvironmentObject var store: SessionStore
    @State private var camera: MapCameraPosition = .region(
        MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: 35.68, longitude: 139.69),
            span: MKCoordinateSpan(latitudeDelta: 0.05, longitudeDelta: 0.05)
        )
    )

    var body: some View {
        ZStack {
            MapReader { proxy in
                Map(position: $camera) {
                    if let o = store.origin {
                        Marker("Start", coordinate: o).tint(.green)
                    }
                    if let d = store.destination {
                        Marker("End", coordinate: d).tint(.red)
                    }
                    if let p = store.currentPosition {
                        Annotation("", coordinate: p) {
                            Circle()
                                .fill(.blue)
                                .frame(width: 14, height: 14)
                                .overlay(Circle().stroke(.white, lineWidth: 2))
                        }
                    }
                    if !store.breadcrumb.isEmpty {
                        MapPolyline(coordinates: store.breadcrumb)
                            .stroke(.green, lineWidth: 4)
                    }
                }
                .onTapGesture { screenPoint in
                    guard let coord = proxy.convert(screenPoint, from: .local) else { return }
                    store.setPin(at: coord)
                }
            }

            // Crosshair overlay when not yet ready, to confirm tap target.
            if store.pinSelectionStage != .ready {
                Image(systemName: "plus.viewfinder")
                    .font(.system(size: 28, weight: .light))
                    .foregroundStyle(.secondary)
                    .allowsHitTesting(false)
            }

            VStack {
                HStack {
                    Spacer()
                    Button {
                        store.resetPins()
                        store.clearBreadcrumb()
                    } label: {
                        Label("Reset pins", systemImage: "xmark.circle.fill")
                            .labelStyle(.iconOnly)
                            .font(.title2)
                            .padding(10)
                            .background(.thinMaterial, in: Circle())
                    }
                    .padding(.top, 12)
                    .padding(.trailing, 12)
                    .accessibilityLabel("Reset pins")
                }
                Spacer()
            }
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add controller-ios/ControllerApp/Views/MapScreen.swift
git commit -m "feat(controller-ios): add MapScreen with two-tap pin selection"
```

---

### Task 8: SearchBar component

**Files:**
- Create: `controller-ios/ControllerApp/Views/SearchBar.swift`

- [ ] **Step 1: Implement SearchBar**

Create `controller-ios/ControllerApp/Views/SearchBar.swift`:

```swift
import SwiftUI
import CoreLocation

struct SearchBar: View {
    let client: BackendClient
    let onPick: (CLLocationCoordinate2D) -> Void

    @State private var query: String = ""
    @State private var results: [SearchResult] = []
    @State private var loading: Bool = false
    @State private var errorMessage: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search address or place", text: $query)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.search)
                    .onSubmit { Task { await runSearch() } }
                if loading {
                    ProgressView().scaleEffect(0.7)
                } else if !query.isEmpty {
                    Button { query = ""; results = [] } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }
                }
            }
            .padding(10)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))

            if let err = errorMessage {
                Text(err).font(.caption).foregroundStyle(.red).padding(.horizontal, 4)
            }

            if !results.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(results) { r in
                        Button {
                            onPick(CLLocationCoordinate2D(latitude: r.lat, longitude: r.lon))
                            query = r.displayName
                            results = []
                        } label: {
                            VStack(alignment: .leading) {
                                Text(r.displayName).font(.subheadline).lineLimit(2)
                                Text(r.type).font(.caption).foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 6)
                            .padding(.horizontal, 8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                        Divider()
                    }
                }
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    private func runSearch() async {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { results = []; return }
        loading = true; errorMessage = nil; defer { loading = false }
        do {
            results = try await client.search(query: q)
            if results.isEmpty { errorMessage = "No results" }
        } catch {
            errorMessage = "Search failed"
            results = []
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add controller-ios/ControllerApp/Views/SearchBar.swift
git commit -m "feat(controller-ios): add SearchBar wired to /api/search"
```

---

### Task 9: SessionControls + speed slider + cooldown alert

**Files:**
- Create: `controller-ios/ControllerApp/Views/SessionControls.swift`

- [ ] **Step 1: Implement SessionControls**

Create `controller-ios/ControllerApp/Views/SessionControls.swift`:

```swift
import SwiftUI

struct SessionControls: View {
    let client: BackendClient
    @EnvironmentObject var store: SessionStore
    @State private var inFlight: Bool = false
    @State private var cooldown: CooldownDetail? = nil
    @State private var errorMessage: String? = nil

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Text("Speed").font(.subheadline)
                Slider(value: $store.speedKmh, in: 0.5...20.0, step: 0.5)
                Text(String(format: "%.1f km/h", store.speedKmh)).font(.subheadline).monospacedDigit()
            }

            HStack(spacing: 8) {
                primaryButton
                if store.state == .running {
                    Button("Pause") { Task { await action { try await client.pause() } } }
                        .buttonStyle(.bordered)
                }
                if store.state == .paused {
                    Button("Resume") { Task { await action { try await client.resume() } } }
                        .buttonStyle(.bordered)
                }
                if [.starting, .running, .paused, .reconnecting].contains(store.state) {
                    Button("Stop", role: .destructive) {
                        Task { await action { try await client.stop() } }
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let err = errorMessage {
                Text(err).font(.caption).foregroundStyle(.red)
            }
        }
        .alert("Cooldown active", isPresented: Binding(get: { cooldown != nil }, set: { if !$0 { cooldown = nil } })) {
            Button("OK", role: .cancel) { cooldown = nil }
            Button("Skip cooldown") {
                Task { await startSession(skipCooldown: true) }
                cooldown = nil
            }
        } message: {
            if let c = cooldown {
                Text("Reason: \(c.reason)\nJump: \(String(format: "%.1f", c.jumpKm)) km\nWait: \(Int(c.requiredWaitS)) s")
            }
        }
    }

    @ViewBuilder
    private var primaryButton: some View {
        let canStart = store.pinSelectionStage == .ready && store.state == .idle
        Button {
            Task { await startSession(skipCooldown: false) }
        } label: {
            Label(inFlight ? "Working…" : "Walk", systemImage: "figure.walk")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(!canStart || inFlight)
    }

    private func startSession(skipCooldown: Bool) async {
        guard let o = store.origin, let d = store.destination else { return }
        store.clearBreadcrumb()
        await action {
            let req = SessionStartRequest(
                startLat: o.latitude, startLon: o.longitude,
                destinations: [Destination(lat: d.latitude, lon: d.longitude)],
                speedKmh: store.speedKmh,
                loop: false,
                skipCooldown: skipCooldown
            )
            _ = try await client.startSession(req)
        }
    }

    private func action(_ block: @escaping () async throws -> Void) async {
        inFlight = true; errorMessage = nil; defer { inFlight = false }
        do {
            try await block()
        } catch BackendError.cooldown(let d) {
            cooldown = d
        } catch BackendError.sessionAlreadyActive(let m) {
            errorMessage = "Session already active: \(m)"
        } catch BackendError.routing(let m) {
            errorMessage = "Routing error: \(m)"
        } catch BackendError.server(let code, let m) {
            errorMessage = "Server \(code): \(m)"
        } catch BackendError.transport(let m) {
            errorMessage = "Network: \(m)"
        } catch {
            errorMessage = "\(error)"
        }
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add controller-ios/ControllerApp/Views/SessionControls.swift
git commit -m "feat(controller-ios): add SessionControls with cooldown alert + speed slider"
```

---

### Task 10: StepCompanionsPanel

**Files:**
- Create: `controller-ios/ControllerApp/Views/StepCompanionsPanel.swift`

- [ ] **Step 1: Implement StepCompanionsPanel**

Create `controller-ios/ControllerApp/Views/StepCompanionsPanel.swift`:

```swift
import SwiftUI

struct StepCompanionsPanel: View {
    @EnvironmentObject var store: SessionStore

    var body: some View {
        let companions = store.latest?.stepCompanions ?? []
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: "shoeprints.fill")
                Text("Step companions").font(.headline)
                Spacer()
                Text("\(companions.count)").foregroundStyle(.secondary).monospacedDigit()
            }
            if companions.isEmpty {
                Text("No step companions connected.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(companions) { c in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(c.label).font(.subheadline)
                            if let udid = c.udid {
                                Text(udid).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                            }
                        }
                        Spacer()
                        Text("\(c.totalAcked) steps").font(.caption).monospacedDigit()
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .padding(10)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add controller-ios/ControllerApp/Views/StepCompanionsPanel.swift
git commit -m "feat(controller-ios): add StepCompanionsPanel"
```

---

### Task 11: RootView + SettingsScreen + ControllerAppApp entry

**Files:**
- Create: `controller-ios/ControllerApp/Views/RootView.swift`
- Create: `controller-ios/ControllerApp/Views/SettingsScreen.swift`
- Create: `controller-ios/ControllerApp/App/ControllerAppApp.swift`

- [ ] **Step 1: Implement SettingsScreen**

Create `controller-ios/ControllerApp/Views/SettingsScreen.swift`:

```swift
import SwiftUI

struct SettingsScreen: View {
    @Binding var config: BackendConfig
    let client: BackendClient
    @State private var urlText: String = ""
    @State private var saving: Bool = false
    @State private var probeMessage: String? = nil
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Backend") {
                    TextField("http://host:port", text: $urlText)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button(saving ? "Testing…" : "Test connection") {
                        Task { await probe() }
                    }
                    .disabled(saving)
                    if let m = probeMessage {
                        Text(m).font(.caption)
                    }
                }
                Section("Build") {
                    Text("ControllerApp · iOS 17+").font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        if let url = URL(string: urlText) {
                            config = BackendConfig(baseURL: url)
                            config.save()
                            Task { await client.updateBaseURL(url) }
                            dismiss()
                        } else {
                            probeMessage = "Invalid URL"
                        }
                    }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .onAppear { urlText = config.baseURL.absoluteString }
        }
    }

    private func probe() async {
        guard let url = URL(string: urlText) else { probeMessage = "Invalid URL"; return }
        saving = true; defer { saving = false }
        let tester = BackendClient(baseURL: url)
        do {
            let snap = try await tester.fetchStatus()
            probeMessage = "OK — state: \(snap.state.rawValue)"
        } catch {
            probeMessage = "Failed: \(error)"
        }
    }
}
```

- [ ] **Step 2: Implement RootView**

Create `controller-ios/ControllerApp/Views/RootView.swift`:

```swift
import SwiftUI

struct RootView: View {
    @StateObject private var store = SessionStore()
    @State private var config: BackendConfig = BackendConfig.loadFromUserDefaults()
    @State private var client: BackendClient
    @State private var subscriber = LiveStatusSubscriber()
    @State private var showSettings = false

    init() {
        let cfg = BackendConfig.loadFromUserDefaults()
        _config = State(initialValue: cfg)
        _client = State(initialValue: BackendClient(baseURL: cfg.baseURL))
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SearchBar(client: client) { coord in
                    store.setPin(at: coord)
                }
                .padding(.horizontal)
                .padding(.top, 8)

                MapScreen()
                    .environmentObject(store)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                VStack(spacing: 10) {
                    SessionControls(client: client).environmentObject(store)
                    StepCompanionsPanel().environmentObject(store)
                }
                .padding(.horizontal)
                .padding(.vertical, 10)
            }
            .navigationTitle("Trail Controller")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    StatePill(state: store.state)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsScreen(config: $config, client: client)
            }
            .task {
                let stream = await subscriber.start(baseURL: config.baseURL)
                for await snap in stream {
                    store.apply(snapshot: snap)
                }
            }
            .onChange(of: config) { _, newConfig in
                Task {
                    await subscriber.cancel()
                    let stream = await subscriber.start(baseURL: newConfig.baseURL)
                    for await snap in stream {
                        store.apply(snapshot: snap)
                    }
                }
            }
        }
    }
}

private struct StatePill: View {
    let state: SessionState
    var body: some View {
        Text(state.rawValue)
            .font(.caption).bold()
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(color.opacity(0.2), in: Capsule())
            .foregroundStyle(color)
    }
    private var color: Color {
        switch state {
        case .running:      return .green
        case .paused:       return .orange
        case .stopping, .reconnecting: return .yellow
        case .error:        return .red
        case .starting:     return .blue
        case .idle:         return .secondary
        case .unknown:      return .secondary
        }
    }
}
```

- [ ] **Step 3: Implement app entry**

Create `controller-ios/ControllerApp/App/ControllerAppApp.swift`:

```swift
import SwiftUI

@main
struct ControllerAppApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}
```

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/Views/RootView.swift \
        controller-ios/ControllerApp/Views/SettingsScreen.swift \
        controller-ios/ControllerApp/App/ControllerAppApp.swift
git commit -m "feat(controller-ios): wire RootView + Settings + app entry"
```

---

## Stage C — Integration & Verification (Tasks 12–14)

### Task 12: Build, sideload, smoke-test on physical iPhone

**Files:**
- None (manual verification)

Performed by the user against a live backend. Requires the user has completed Task 1's Xcode scaffold and the project builds.

- [ ] **Step 1: Build in Xcode**

In Xcode: select **ControllerApp** scheme → choose a physical iPhone as run destination → ⌘B. Fix any signing issues using the same Apple ID flow as `companion-ios`.

- [ ] **Step 2: Start backend on Mac**

```bash
cd /Users/jl26/habitDevs/trail-simulator
uv run trail-simulator --host 0.0.0.0 --port 8787
```

- [ ] **Step 3: Run app on iPhone via ⌘R, then in Settings set backend URL to Mac's LAN IP (e.g. `http://192.168.1.50:8787`) and tap Test connection**

Expected: "OK — state: idle".

- [ ] **Step 4: Run the verification golden path**

1. Tap a point on the map → green Start marker appears.
2. Tap another point → red End marker appears.
3. Confirm speed slider reads ~4 km/h.
4. Tap Walk → state pill goes idle → starting → running.
5. Watch position marker animate along route; green breadcrumb traces behind.
6. Tap Pause → state pill goes paused, position freezes; breadcrumb stops extending.
7. Tap Resume → state pill goes running; breadcrumb extends.
8. Tap Stop → state pill goes stopping → idle; breadcrumb retained on map until Reset pins is pressed.
9. Tap Reset pins → markers cleared, breadcrumb cleared.

- [ ] **Step 5: Run the verification edge cases**

1. **Cooldown 429**: With a recent session just stopped, immediately tap pins far away from previous route and Walk → cooldown alert should appear with required_wait_s, jump_km, reason. Tap "Skip cooldown" → session starts.
2. **Address search**: Type "Tokyo Station" in search bar, press search → results list appears → tap first result → map jumps and a pin drops as Start (or Destination if Start already set).
3. **Multi-device step companions**: With the StepCompanion app connected on another iPhone, run a route; StepCompanionsPanel should list the companion with non-zero `total_acked` after a few seconds.
4. **WebSocket reconnect**: Kill backend mid-route; state pill should transition to reconnecting (if backend is restarted) or hold last snapshot. Restart backend; state should resume.
5. **Web UI parity**: Open the web UI on the Mac in parallel; both should reflect the same state from the same session.

- [ ] **Step 6: Record findings**

Add a short verification log to `controller-ios/docs/phase-1-verification.md` with PASS / FAIL per check and any observed issues. Commit it.

```bash
git add controller-ios/docs/phase-1-verification.md
git commit -m "docs(controller-ios): record Phase 1 on-device verification"
```

---

### Task 13: Senior Developer review pass

Performed by the orchestrator (Senior Developer agent) — not by the Mobile App Builder.

- [ ] **Step 1: Re-read each Mobile App Builder commit** and verify each file matches the plan's intent (file paths, types, function names, breadcrumb gating invariant).

- [ ] **Step 2: Check that the file structure matches the plan's File Structure section** — no rogue files, no missed files, no scope creep.

- [ ] **Step 3: Run the full test suite** on the Mac:

```bash
xcodebuild test -project controller-ios/ControllerApp.xcodeproj -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -30
```
Expected: all tests pass.

- [ ] **Step 4: Spot-check Swift code quality**

- All actors are used where stated; no `@MainActor` violations or hidden `Sendable` problems.
- Error mapping in `BackendClient.checkOk` matches the API contract for 409/429/502.
- Breadcrumb gating in `SessionStore.apply` uses the static `activeStates` set — not duplicated inline.
- No force-unwraps except where the URL construction is guaranteed safe (already justified inline).

- [ ] **Step 5: Approve or request changes**

If issues are found, write them to `docs/superpowers/reviews/2026-05-18-controller-ios-phase-1-review.md`, list each issue with file:line, and route back to the Mobile App Builder. Loop until clean.

---

### Task 14: controller-ios/README.md

Performed by the Technical Writer agent. The deliverable mirrors `companion-ios/README.md`'s structure.

**Files:**
- Create: `controller-ios/README.md`

- [ ] **Step 1: Write README**

Create `controller-ios/README.md` with the following sections:

```markdown
# TrailController — Xcode Setup & Sideload Guide

TrailController is a sideloaded iOS app that replaces the trail-simulator web UI with a native experience. It connects to the trail-simulator backend over LAN (HTTP + WebSocket) and lets you drive GPS spoofing sessions from your iPhone. A free Apple ID is sufficient for sideloading.

## 1. Create the Xcode project

[Follow the same numbered steps as companion-ios/README.md §1, with these substitutions:]
- Product Name: `ControllerApp`
- Bundle Identifier: e.g. `com.yourname.trailcontroller`
- Save location: `controller-ios/`
- Deployment target: **iOS 17.0**

## 2. Add the Swift sources

Delete the placeholders Xcode generated. Drag in the folders inside `controller-ios/ControllerApp/`:
`App/`, `Models/`, `Network/`, `Store/`, `Views/`, `Resources/`.
Add the test target `ControllerAppTests/` pointing at `controller-ios/ControllerAppTests/`.

## 3. Set the Info.plist path

Build Settings → search "Info.plist" → set **Info.plist File** to `ControllerApp/Resources/Info.plist`.

## 4. Signing

Same as companion-ios §5. Set Team to your Apple ID, automatic signing on, unique bundle id.

## 5. Sideload

Same as companion-ios §6.

## 6. Run the app

1. On Mac, start the backend bound to LAN:
   ```bash
   uv run trail-simulator --host 0.0.0.0 --port 8787
   ```
2. On iPhone, open TrailController → tap the gear → set Backend URL to Mac's LAN IP (e.g. `http://192.168.1.50:8787`) → Save.
3. Tap two map pins → set speed → tap Walk.

## 7. Verification protocol

Run the golden-path and edge-case checks from `controller-ios/docs/phase-1-verification.md`.

## 8. Relationship to the web UI

The web UI at `http://<mac-ip>:8787/` continues to work in parallel. Anything you do in the iOS app is visible there and vice versa, because both clients consume the same `StatusSnapshot` stream.

## 9. Known limits

- Free Apple ID sideloads expire after 7 days; re-run from Xcode to refresh.
- No authentication on the backend — works on trusted LANs only. Remote operation requires Phase 3 hardening.
- No offline mode; the app expects continuous WebSocket reachability to the backend.

## 10. Troubleshooting

- **"OK" probe fails**: confirm backend is bound to `0.0.0.0`, not `127.0.0.1`. Check Mac firewall (System Settings → Network → Firewall) isn't blocking port 8787.
- **State pill stuck on idle**: backend is reachable but WebSocket isn't connecting. Verify by opening `http://<mac-ip>:8787/` in Safari and checking the web UI works.
- **Cooldown alert keeps appearing**: backend's SQLite cooldown table tracks the last route's tail position. Tap Skip cooldown to bypass for testing, or wait the displayed `required_wait_s`.
```

- [ ] **Step 2: Commit**

```bash
git add controller-ios/README.md
git commit -m "docs(controller-ios): add sideload + verification guide"
```

---

## Subagent Dispatch Map

| Task | Primary agent | Reviewer | Parallel with |
|---|---|---|---|
| 1 | (User manual) | — | — |
| 2 | Explore / general-purpose | Senior Developer | — |
| 3 | Mobile App Builder | Senior Developer | — |
| 4 | Mobile App Builder | Senior Developer | — |
| 5 | Mobile App Builder | Senior Developer | — |
| 6 | Mobile App Builder | Senior Developer | — |
| 7 | Mobile App Builder | Senior Developer | 8, 9, 10 |
| 8 | Mobile App Builder | Senior Developer | 7, 9, 10 |
| 9 | Mobile App Builder | Senior Developer | 7, 8, 10 |
| 10 | Mobile App Builder | Senior Developer | 7, 8, 9 |
| 11 | Mobile App Builder | Senior Developer | — (depends on 7–10) |
| 12 | (User manual) | — | — |
| 13 | Senior Developer | — | — |
| 14 | Technical Writer | Senior Developer | — |

Stage B (Tasks 7–10) are dispatched in parallel using the `dispatching-parallel-agents` pattern after Stage A is fully merged. Task 11 collects them and depends on all four. Task 13 (review) runs after 12 (or earlier on the per-task git diff, depending on orchestration cadence).
