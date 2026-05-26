# Merge StepCompanion into ControllerApp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Absorb the standalone `companion-ios/StepCompanion` app into the existing `controller-ios/ControllerApp` Xcode project so a single sideloaded build runs both the controller UI and the local HealthKit step writer.

**Architecture:** Add a `Health/` source folder to the ControllerApp target with the three ported StepCompanion files (`StepClient`, `HealthWriter`, `BackgroundAudioKeeper`) plus a new `HealthStore` that owns the toggle + counters. Replace `RootView`'s linear layout with a 3-tab `TabView` (Map / Health / Settings). Add HealthKit capability + `audio` background mode to the existing target. Two WebSockets (`/ws/live`, `/ws/steps`) run concurrently against the same `BackendConfig.baseURL`.

**Tech Stack:** Swift 5, SwiftUI, HealthKit, AVFoundation, URLSessionWebSocketTask, XCTest. Xcode 16+, iOS 17+ deployment target.

**Spec:** `docs/superpowers/specs/2026-05-26-merge-ios-apps-design.md`

---

## File Structure (created/modified)

**New source files:**
- `controller-ios/ControllerApp/ControllerApp/Health/StepClient.swift`
- `controller-ios/ControllerApp/ControllerApp/Health/HealthWriter.swift`
- `controller-ios/ControllerApp/ControllerApp/Health/BackgroundAudioKeeper.swift`
- `controller-ios/ControllerApp/ControllerApp/Health/HealthStore.swift`
- `controller-ios/ControllerApp/ControllerApp/Models/StepEvent.swift`
- `controller-ios/ControllerApp/ControllerApp/Views/HealthTabView.swift`
- `controller-ios/ControllerApp/ControllerApp/Views/MapTabView.swift`
- `controller-ios/ControllerApp/ControllerApp/Views/SettingsTabView.swift`
- `controller-ios/ControllerApp/ControllerApp/Resources/ControllerApp.entitlements`

**Modified source files:**
- `controller-ios/ControllerApp/ControllerApp/App/ControllerAppApp.swift` — create HealthStore + BackgroundAudioKeeper, inject, request HK auth.
- `controller-ios/ControllerApp/ControllerApp/Views/RootView.swift` — replace body with TabView referencing the three tab views.
- `controller-ios/ControllerApp/ControllerApp/Views/StepCompanionsPanel.swift` — repurpose to "This Device" row reading from HealthStore.
- `controller-ios/ControllerApp/ControllerApp/Resources/Info.plist` — add UIBackgroundModes audio, NSHealthShare/UpdateUsageDescription.
- `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj` — register new files, add HealthKit capability, point entitlements file, link HealthKit.framework + AVFoundation.framework.

**New test files:**
- `controller-ios/ControllerApp/ControllerAppTests/StepEventDecodingTests.swift`
- `controller-ios/ControllerApp/ControllerAppTests/HealthStoreTests.swift`
- `controller-ios/ControllerApp/ControllerAppTests/StepClientURLBuildingTests.swift`

**Deleted (final task):**
- `companion-ios/` (entire folder).

---

## Task 1: Add HealthKit framework dependency + entitlements file

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Resources/ControllerApp.entitlements`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`

- [ ] **Step 1: Create entitlements file**

Write `controller-ios/ControllerApp/ControllerApp/Resources/ControllerApp.entitlements` with:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.developer.healthkit</key>
    <true/>
</dict>
</plist>
```

- [ ] **Step 2: Wire entitlements + HealthKit capability into the Xcode project**

Edit `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`:
1. In both Debug and Release `XCBuildConfiguration` blocks for the `ControllerApp` target, add:
   `CODE_SIGN_ENTITLEMENTS = ControllerApp/Resources/ControllerApp.entitlements;`
2. Add `HealthKit.framework` to the `Frameworks` build phase (PBXFrameworksBuildPhase) and to `PBXFileReference` section under group `Frameworks` (create the group if absent). Use file ref pattern matching existing system framework refs in the file.
3. Add a `SystemCapabilities` dictionary entry under the target's `attributes` block:
   ```
   SystemCapabilities = {
       com.apple.HealthKit = { enabled = 1; };
   };
   ```

If pbxproj edits prove too brittle, open the project in Xcode and add Capability → HealthKit via the UI, then commit the resulting pbxproj diff.

- [ ] **Step 3: Build to verify no signing/linker break**

Run from repo root:
```bash
xcodebuild -project controller-ios/ControllerApp/ControllerApp.xcodeproj \
  -scheme ControllerApp \
  -destination 'generic/platform=iOS Simulator' \
  -configuration Debug \
  build CODE_SIGNING_ALLOWED=NO
```

Expected: `BUILD SUCCEEDED`. No reference to HealthKit in code yet, but the framework must link.

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Resources/ControllerApp.entitlements \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): add HealthKit capability and entitlements file"
```

---

## Task 2: Add background-audio + HealthKit usage strings to Info.plist

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Resources/Info.plist`

- [ ] **Step 1: Add three keys to Info.plist**

Open `controller-ios/ControllerApp/ControllerApp/Resources/Info.plist` and add inside the top-level `<dict>`:

```xml
<key>UIBackgroundModes</key>
<array>
    <string>audio</string>
</array>
<key>NSHealthShareUsageDescription</key>
<string>This app reads HealthKit authorization status so it can show whether step writes are enabled.</string>
<key>NSHealthUpdateUsageDescription</key>
<string>This app writes step count and walking distance from trail-simulator sessions to HealthKit.</string>
```

- [ ] **Step 2: Build**

Run the same xcodebuild command from Task 1 step 3.
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 3: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Resources/Info.plist
git commit -m "feat(controller-ios): declare background audio mode and HealthKit usage strings"
```

---

## Task 3: Port `BackgroundAudioKeeper` into ControllerApp

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Health/BackgroundAudioKeeper.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj` (register file)

- [ ] **Step 1: Create the Health/ folder and source file**

Write `controller-ios/ControllerApp/ControllerApp/Health/BackgroundAudioKeeper.swift` (identical to the StepCompanion version):

```swift
import AVFoundation

// Plays a silent looping buffer to keep the app process alive in background
// so the /ws/live + /ws/steps WebSockets and HealthKit writes survive when
// the user switches apps. Requires the "Audio, AirPlay, and Picture in Picture"
// background mode capability.
final class BackgroundAudioKeeper {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()

    func start() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try session.setActive(true)
        } catch {
            return
        }

        guard let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 1) else {
            return
        }
        let frames: AVAudioFrameCount = 44100
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else {
            return
        }
        buffer.frameLength = frames

        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        do {
            try engine.start()
        } catch {
            return
        }
        player.scheduleBuffer(buffer, at: nil, options: .loops, completionHandler: nil)
        player.play()
    }
}
```

- [ ] **Step 2: Register the file in pbxproj**

Edit `project.pbxproj`:
1. Add a `PBXFileReference` for `BackgroundAudioKeeper.swift` (mirror an existing Swift file ref like `SessionStore.swift`).
2. Add it to the `Sources` build phase (PBXSourcesBuildPhase).
3. Create a `PBXGroup` named `Health` under the `ControllerApp` group and add the file to it.

(Same fallback as Task 1: if pbxproj editing is awkward, drag the new file into the Xcode project navigator and commit the resulting pbxproj diff.)

- [ ] **Step 3: Build**

```bash
xcodebuild -project controller-ios/ControllerApp/ControllerApp.xcodeproj \
  -scheme ControllerApp -destination 'generic/platform=iOS Simulator' \
  -configuration Debug build CODE_SIGNING_ALLOWED=NO
```
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Health/BackgroundAudioKeeper.swift \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): port BackgroundAudioKeeper for background WebSocket survival"
```

---

## Task 4: Port `HealthWriter` into ControllerApp

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Health/HealthWriter.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`

- [ ] **Step 1: Create file**

Write `controller-ios/ControllerApp/ControllerApp/Health/HealthWriter.swift`:

```swift
import Foundation
import Combine
import HealthKit

@MainActor
final class HealthWriter: ObservableObject {
    private let store = HKHealthStore()
    @Published var authorized = false
    @Published var lastError: String?

    private var writeTypes: Set<HKSampleType> {
        [
            HKQuantityType(.stepCount),
            HKQuantityType(.distanceWalkingRunning),
        ]
    }

    func requestAuthorization() async {
        guard HKHealthStore.isHealthDataAvailable() else {
            lastError = "HealthKit not available on this device"
            return
        }
        do {
            try await store.requestAuthorization(toShare: writeTypes, read: [])
            authorized = true
        } catch {
            lastError = "HealthKit auth failed: \(error.localizedDescription)"
        }
    }

    func writeSteps(count: Int, distanceMeters: Double, end: Date) async {
        let start = end.addingTimeInterval(-Double(count))
        let stepType = HKQuantityType(.stepCount)
        let stepSample = HKQuantitySample(
            type: stepType,
            quantity: HKQuantity(unit: .count(), doubleValue: Double(count)),
            start: start,
            end: end
        )
        let distType = HKQuantityType(.distanceWalkingRunning)
        let distSample = HKQuantitySample(
            type: distType,
            quantity: HKQuantity(unit: .meter(), doubleValue: distanceMeters),
            start: start,
            end: end
        )
        do {
            try await store.save([stepSample, distSample])
        } catch {
            lastError = "write failed: \(error.localizedDescription)"
        }
    }
}
```

(Note: `writeDebugSample` from the original is intentionally dropped — not in spec.)

- [ ] **Step 2: Register in pbxproj** (same pattern as Task 3 Step 2).

- [ ] **Step 3: Build** (same command).
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 4: Commit**
```bash
git add controller-ios/ControllerApp/ControllerApp/Health/HealthWriter.swift \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): port HealthWriter for HealthKit step/distance writes"
```

---

## Task 5: Add `StepEvent` model

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Models/StepEvent.swift`
- Create: `controller-ios/ControllerApp/ControllerAppTests/StepEventDecodingTests.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`

- [ ] **Step 1: Write failing test**

Create `controller-ios/ControllerApp/ControllerAppTests/StepEventDecodingTests.swift`:

```swift
import XCTest
@testable import ControllerApp

final class StepEventDecodingTests: XCTestCase {
    func testDecodeStepsEvent() throws {
        let json = #"{"type":"steps","steps":42,"distance_m":31.5,"ts":"2026-05-26T12:00:00Z"}"#
        let data = Data(json.utf8)
        let event = try JSONDecoder().decode(StepEvent.self, from: data)
        XCTAssertEqual(event.type, "steps")
        XCTAssertEqual(event.steps, 42)
        XCTAssertEqual(event.distance_m, 31.5)
        XCTAssertEqual(event.ts, "2026-05-26T12:00:00Z")
    }

    func testDecodeMissingOptionalFields() throws {
        let json = #"{"type":"hello"}"#
        let data = Data(json.utf8)
        let event = try JSONDecoder().decode(StepEvent.self, from: data)
        XCTAssertEqual(event.type, "hello")
        XCTAssertNil(event.steps)
        XCTAssertNil(event.distance_m)
        XCTAssertNil(event.ts)
    }
}
```

- [ ] **Step 2: Run test, expect failure**

Run:
```bash
xcodebuild -project controller-ios/ControllerApp/ControllerApp.xcodeproj \
  -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 17' \
  test -only-testing:ControllerAppTests/StepEventDecodingTests
```
Expected: build failure — `cannot find 'StepEvent' in scope`.

- [ ] **Step 3: Implement `StepEvent`**

Create `controller-ios/ControllerApp/ControllerApp/Models/StepEvent.swift`:

```swift
import Foundation

struct StepEvent: Decodable {
    let type: String
    let steps: Int?
    let distance_m: Double?
    let ts: String?
}
```

- [ ] **Step 4: Register both files in pbxproj** (StepEvent.swift in `Sources` of ControllerApp; test file in `Sources` of ControllerAppTests).

- [ ] **Step 5: Run tests, expect pass**

Same command as Step 2. Expected: 2 tests passing.

- [ ] **Step 6: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Models/StepEvent.swift \
        controller-ios/ControllerApp/ControllerAppTests/StepEventDecodingTests.swift \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): add StepEvent model with decoding tests"
```

---

## Task 6: Port `StepClient` with URL-building helper

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Health/StepClient.swift`
- Create: `controller-ios/ControllerApp/ControllerAppTests/StepClientURLBuildingTests.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`

- [ ] **Step 1: Write failing URL-building test**

Create `controller-ios/ControllerApp/ControllerAppTests/StepClientURLBuildingTests.swift`:

```swift
import XCTest
@testable import ControllerApp

final class StepClientURLBuildingTests: XCTestCase {
    func testStepsURLFromHTTPBase() {
        let base = URL(string: "http://192.168.0.63:8080")!
        let ws = StepClient.stepsURL(from: base)
        XCTAssertEqual(ws?.absoluteString, "ws://192.168.0.63:8080/ws/steps")
    }

    func testStepsURLFromHTTPSBase() {
        let base = URL(string: "https://example.com")!
        let ws = StepClient.stepsURL(from: base)
        XCTAssertEqual(ws?.absoluteString, "wss://example.com/ws/steps")
    }
}
```

- [ ] **Step 2: Run test, expect failure**

```bash
xcodebuild -project controller-ios/ControllerApp/ControllerApp.xcodeproj \
  -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 17' \
  test -only-testing:ControllerAppTests/StepClientURLBuildingTests
```
Expected: `cannot find 'StepClient' in scope`.

- [ ] **Step 3: Implement `StepClient`**

Create `controller-ios/ControllerApp/ControllerApp/Health/StepClient.swift`:

```swift
import Foundation
import Combine
import UIKit

@MainActor
final class StepClient: ObservableObject {
    @Published var connected = false
    @Published var lastError: String?

    private var task: URLSessionWebSocketTask?
    private var onEvent: ((StepEvent) -> Void)?

    static func stepsURL(from base: URL) -> URL? {
        var comps = URLComponents(url: base, resolvingAgainstBaseURL: false)
        guard let scheme = comps?.scheme?.lowercased() else { return nil }
        switch scheme {
        case "http":  comps?.scheme = "ws"
        case "https": comps?.scheme = "wss"
        case "ws", "wss": break
        default: return nil
        }
        comps?.path = "/ws/steps"
        return comps?.url
    }

    func connect(baseURL: URL, label: String, onEvent: @escaping (StepEvent) -> Void) {
        guard let url = Self.stepsURL(from: baseURL) else {
            lastError = "invalid base URL"
            return
        }
        self.onEvent = onEvent
        task?.cancel(with: .normalClosure, reason: nil)
        let session = URLSession(configuration: .default)
        task = session.webSocketTask(with: url)
        task?.resume()

        Task { @MainActor in
            let hello: [String: String] = ["type": "hello", "device_label": label, "udid": ""]
            if let data = try? JSONSerialization.data(withJSONObject: hello),
               let text = String(data: data, encoding: .utf8) {
                try? await task?.send(.string(text))
            }
            connected = true
            receive()
            scheduleHeartbeat()
        }
    }

    func disconnect() {
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        connected = false
    }

    private func receive() {
        task?.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch result {
                case .failure(let error):
                    self.lastError = error.localizedDescription
                    self.connected = false
                case .success(let msg):
                    if case .string(let text) = msg, let data = text.data(using: .utf8),
                       let event = try? JSONDecoder().decode(StepEvent.self, from: data) {
                        self.onEvent?(event)
                    }
                    self.receive()
                }
            }
        }
    }

    private func scheduleHeartbeat() {
        Task { @MainActor in
            while connected {
                try? await Task.sleep(for: .seconds(10))
                guard connected else { break }
                let payload = "{\"type\":\"heartbeat\"}"
                try? await task?.send(.string(payload))
            }
        }
    }
}
```

- [ ] **Step 4: Register files in pbxproj**.

- [ ] **Step 5: Run URL test, expect pass**

```bash
xcodebuild -project controller-ios/ControllerApp/ControllerApp.xcodeproj \
  -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 17' \
  test -only-testing:ControllerAppTests/StepClientURLBuildingTests
```
Expected: 2 tests passing.

- [ ] **Step 6: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Health/StepClient.swift \
        controller-ios/ControllerApp/ControllerAppTests/StepClientURLBuildingTests.swift \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): port StepClient with WS URL builder"
```

---

## Task 7: Build `HealthStore` (toggle, counters, persistence)

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Health/HealthStore.swift`
- Create: `controller-ios/ControllerApp/ControllerAppTests/HealthStoreTests.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`

- [ ] **Step 1: Write failing tests**

Create `controller-ios/ControllerApp/ControllerAppTests/HealthStoreTests.swift`:

```swift
import XCTest
@testable import ControllerApp

@MainActor
final class HealthStoreTests: XCTestCase {
    private var defaults: UserDefaults!

    override func setUp() async throws {
        defaults = UserDefaults(suiteName: "HealthStoreTests.\(UUID().uuidString)")!
    }

    func testDefaultsEnabledTrueAndZeroCounters() {
        let store = HealthStore(defaults: defaults)
        XCTAssertTrue(store.enabled)
        XCTAssertEqual(store.sessionSteps, 0)
        XCTAssertEqual(store.sessionDistanceM, 0)
        XCTAssertEqual(store.cumulativeSteps, 0)
        XCTAssertEqual(store.cumulativeDistanceM, 0)
    }

    func testApplyStepsEventIncrementsSessionAndCumulative() {
        let store = HealthStore(defaults: defaults)
        let event = StepEvent(type: "steps", steps: 10, distance_m: 7.5, ts: nil)
        store.apply(event: event)
        XCTAssertEqual(store.sessionSteps, 10)
        XCTAssertEqual(store.sessionDistanceM, 7.5, accuracy: 0.001)
        XCTAssertEqual(store.cumulativeSteps, 10)
        XCTAssertEqual(store.cumulativeDistanceM, 7.5, accuracy: 0.001)
    }

    func testNonStepsEventIgnored() {
        let store = HealthStore(defaults: defaults)
        store.apply(event: StepEvent(type: "hello", steps: nil, distance_m: nil, ts: nil))
        XCTAssertEqual(store.sessionSteps, 0)
        XCTAssertEqual(store.cumulativeSteps, 0)
    }

    func testCumulativePersistsAcrossInits() {
        let s1 = HealthStore(defaults: defaults)
        s1.apply(event: StepEvent(type: "steps", steps: 5, distance_m: 4.0, ts: nil))
        let s2 = HealthStore(defaults: defaults)
        XCTAssertEqual(s2.cumulativeSteps, 5)
        XCTAssertEqual(s2.cumulativeDistanceM, 4.0, accuracy: 0.001)
        XCTAssertEqual(s2.sessionSteps, 0, "session counters do not persist")
    }

    func testTogglingEnabledResetsSession() {
        let store = HealthStore(defaults: defaults)
        store.apply(event: StepEvent(type: "steps", steps: 5, distance_m: 4.0, ts: nil))
        store.enabled = false
        store.enabled = true
        XCTAssertEqual(store.sessionSteps, 0)
        XCTAssertEqual(store.sessionDistanceM, 0)
    }
}

// Test-visible initializer for StepEvent (synthesized one is internal already)
extension StepEvent {
    init(type: String, steps: Int?, distance_m: Double?, ts: String?) {
        self.type = type
        self.steps = steps
        self.distance_m = distance_m
        self.ts = ts
    }
}
```

Note: the explicit memberwise init on `StepEvent` will conflict with the auto-synthesized one only if the struct already has a different one — here `StepEvent`'s synthesized memberwise init is internal, so adding the same explicit one in an extension may collide. If the test build complains, delete the extension and use a `@testable` factory helper in `StepEvent` source instead. (See Step 3.)

- [ ] **Step 2: Run tests, expect failure**

```bash
xcodebuild -project controller-ios/ControllerApp/ControllerApp.xcodeproj \
  -scheme ControllerApp -destination 'platform=iOS Simulator,name=iPhone 17' \
  test -only-testing:ControllerAppTests/HealthStoreTests
```
Expected: `cannot find 'HealthStore'`.

- [ ] **Step 3: Implement `HealthStore`**

Create `controller-ios/ControllerApp/ControllerApp/Health/HealthStore.swift`:

```swift
import Foundation
import Combine

@MainActor
final class HealthStore: ObservableObject {
    @Published var enabled: Bool {
        didSet {
            defaults.set(enabled, forKey: Keys.enabled)
            if enabled != oldValue {
                sessionSteps = 0
                sessionDistanceM = 0
            }
        }
    }
    @Published private(set) var sessionSteps: Int = 0
    @Published private(set) var sessionDistanceM: Double = 0
    @Published private(set) var cumulativeSteps: Int
    @Published private(set) var cumulativeDistanceM: Double

    let writer: HealthWriter
    let client: StepClient

    private let defaults: UserDefaults

    private enum Keys {
        static let enabled = "health.enabled"
        static let cumulativeSteps = "health.cumulativeSteps"
        static let cumulativeDistanceM = "health.cumulativeDistanceM"
    }

    init(defaults: UserDefaults = .standard,
         writer: HealthWriter = HealthWriter(),
         client: StepClient = StepClient()) {
        self.defaults = defaults
        self.writer = writer
        self.client = client
        self.enabled = defaults.object(forKey: Keys.enabled) as? Bool ?? true
        self.cumulativeSteps = defaults.integer(forKey: Keys.cumulativeSteps)
        self.cumulativeDistanceM = defaults.double(forKey: Keys.cumulativeDistanceM)
    }

    func apply(event: StepEvent) {
        guard event.type == "steps",
              let n = event.steps, n > 0,
              let dist = event.distance_m else { return }
        sessionSteps += n
        sessionDistanceM += dist
        cumulativeSteps += n
        cumulativeDistanceM += dist
        defaults.set(cumulativeSteps, forKey: Keys.cumulativeSteps)
        defaults.set(cumulativeDistanceM, forKey: Keys.cumulativeDistanceM)
        if enabled && writer.authorized {
            Task { await writer.writeSteps(count: n, distanceMeters: dist, end: Date()) }
        }
    }

    func connect(baseURL: URL, label: String) {
        guard enabled, writer.authorized else { return }
        client.connect(baseURL: baseURL, label: label) { [weak self] event in
            Task { @MainActor [weak self] in self?.apply(event: event) }
        }
    }

    func disconnect() {
        client.disconnect()
    }

    func reconnect(baseURL: URL, label: String) {
        disconnect()
        connect(baseURL: baseURL, label: label)
    }
}
```

- [ ] **Step 4: Run tests, expect pass**

If the `StepEvent` extension in the test file collides, replace the test file's extension block with a static factory in `Models/StepEvent.swift`:

```swift
#if DEBUG
extension StepEvent {
    static func makeForTest(type: String, steps: Int? = nil, distance_m: Double? = nil, ts: String? = nil) -> StepEvent {
        let json = """
        {"type":"\(type)","steps":\(steps.map(String.init) ?? "null"),"distance_m":\(distance_m.map(String.init) ?? "null"),"ts":\(ts.map { "\"\($0)\"" } ?? "null")}
        """
        return try! JSONDecoder().decode(StepEvent.self, from: Data(json.utf8))
    }
}
#endif
```
…and switch the test file to use `StepEvent.makeForTest(...)`.

Re-run the test command from Step 2.
Expected: 5 tests passing.

- [ ] **Step 5: Register files in pbxproj**.

- [ ] **Step 6: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Health/HealthStore.swift \
        controller-ios/ControllerApp/ControllerAppTests/HealthStoreTests.swift \
        controller-ios/ControllerApp/ControllerApp/Models/StepEvent.swift \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): add HealthStore with toggle, session/cumulative counters"
```

---

## Task 8: Add `HealthTabView`

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Views/HealthTabView.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`

- [ ] **Step 1: Create the view**

Write `controller-ios/ControllerApp/ControllerApp/Views/HealthTabView.swift`:

```swift
import SwiftUI

struct HealthTabView: View {
    @EnvironmentObject var health: HealthStore
    @ObservedObject private var writerProxy: HealthWriter
    @ObservedObject private var clientProxy: StepClient

    init(health: HealthStore) {
        self.writerProxy = health.writer
        self.clientProxy = health.client
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("HealthKit") {
                    HStack {
                        Circle()
                            .fill(writerProxy.authorized ? .green : .red)
                            .frame(width: 10, height: 10)
                        Text(writerProxy.authorized ? "Granted" : "Pending")
                    }
                    if !writerProxy.authorized {
                        Button("Request HealthKit permission") {
                            Task { await writerProxy.requestAuthorization() }
                        }
                    }
                }

                Section("Step writing") {
                    Toggle("Write steps to HealthKit", isOn: $health.enabled)
                        .disabled(!writerProxy.authorized)
                    HStack {
                        Circle()
                            .fill(clientProxy.connected ? .green : .gray)
                            .frame(width: 8, height: 8)
                        Text(clientProxy.connected ? "Connected to /ws/steps" : "Disconnected")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("This session") {
                    LabeledContent("Steps", value: "\(health.sessionSteps)")
                    LabeledContent("Distance",
                                   value: String(format: "%.1f m", health.sessionDistanceM))
                }

                Section("Cumulative") {
                    LabeledContent("Steps", value: "\(health.cumulativeSteps)")
                    LabeledContent("Distance",
                                   value: String(format: "%.1f m", health.cumulativeDistanceM))
                }

                if let err = clientProxy.lastError ?? writerProxy.lastError {
                    Section("Error") {
                        Text(err).foregroundStyle(.red).font(.caption)
                    }
                }
            }
            .navigationTitle("Health")
        }
    }
}
```

- [ ] **Step 2: Register file in pbxproj**.

- [ ] **Step 3: Build**
Same xcodebuild build command as Task 1 Step 3.
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 4: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/HealthTabView.swift \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): add HealthTabView with auth, toggle, and counters"
```

---

## Task 9: Extract current `RootView` body into `MapTabView` and `SettingsTabView`

**Files:**
- Create: `controller-ios/ControllerApp/ControllerApp/Views/MapTabView.swift`
- Create: `controller-ios/ControllerApp/ControllerApp/Views/SettingsTabView.swift`
- Modify: `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj`

- [ ] **Step 1: Create `MapTabView`**

Write `controller-ios/ControllerApp/ControllerApp/Views/MapTabView.swift`:

```swift
import SwiftUI

struct MapTabView: View {
    @EnvironmentObject var store: SessionStore
    let client: BackendClient

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SearchBar(client: client) { coord in
                    store.setPin(at: coord)
                }
                .padding(.horizontal)
                .padding(.top, 8)

                MapScreen()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                VStack(spacing: 10) {
                    SessionControls(client: client)
                    StepCompanionsPanel()
                }
                .padding(.horizontal)
                .padding(.vertical, 10)
            }
            .navigationTitle("Trail Controller")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    MapStatePill(state: store.state)
                }
            }
        }
    }
}

private struct MapStatePill: View {
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

- [ ] **Step 2: Create `SettingsTabView`**

Write `controller-ios/ControllerApp/ControllerApp/Views/SettingsTabView.swift`:

```swift
import SwiftUI

struct SettingsTabView: View {
    @Binding var config: BackendConfig
    let client: BackendClient

    var body: some View {
        SettingsScreen(config: $config, client: client)
    }
}
```

(`SettingsScreen` already wraps itself in `NavigationStack`, so this wrapper is a thin pass-through that future-proofs the tab.)

- [ ] **Step 3: Register both files in pbxproj**.

- [ ] **Step 4: Build**
Expected: `BUILD SUCCEEDED`. (RootView is not yet rewired, but the new views must compile standalone.)

- [ ] **Step 5: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/MapTabView.swift \
        controller-ios/ControllerApp/ControllerApp/Views/SettingsTabView.swift \
        controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj
git commit -m "feat(controller-ios): extract MapTabView and SettingsTabView"
```

---

## Task 10: Rewrite `RootView` as TabView host

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Views/RootView.swift`

- [ ] **Step 1: Replace `RootView.swift` contents**

Overwrite `controller-ios/ControllerApp/ControllerApp/Views/RootView.swift` with:

```swift
import SwiftUI

struct RootView: View {
    @StateObject private var store = SessionStore()
    @EnvironmentObject var health: HealthStore
    @State private var config: BackendConfig = BackendConfig.loadFromUserDefaults()
    @State private var client: BackendClient
    @State private var subscriber = LiveStatusSubscriber()

    init() {
        let cfg = BackendConfig.loadFromUserDefaults()
        _config = State(initialValue: cfg)
        _client = State(initialValue: BackendClient(baseURL: cfg.baseURL))
    }

    var body: some View {
        TabView {
            MapTabView(client: client)
                .environmentObject(store)
                .tabItem { Label("Map", systemImage: "map") }

            HealthTabView(health: health)
                .tabItem { Label("Health", systemImage: "heart.text.square") }

            SettingsTabView(config: $config, client: client)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .task {
            let stream = await subscriber.start(baseURL: config.baseURL)
            health.connect(baseURL: config.baseURL, label: UIDevice.current.name)
            for await snap in stream {
                store.apply(snapshot: snap)
            }
        }
        .onChange(of: config) { _, newConfig in
            Task {
                await subscriber.cancel()
                health.reconnect(baseURL: newConfig.baseURL, label: UIDevice.current.name)
                let stream = await subscriber.start(baseURL: newConfig.baseURL)
                for await snap in stream {
                    store.apply(snapshot: snap)
                }
            }
        }
    }
}
```

(Note: `UIDevice` requires `import UIKit`. SwiftUI re-exports it, but add `import UIKit` explicitly at the top if the build complains.)

- [ ] **Step 2: Build**
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 3: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/RootView.swift
git commit -m "feat(controller-ios): convert RootView to 3-tab Map/Health/Settings layout"
```

---

## Task 11: Wire `HealthStore` + `BackgroundAudioKeeper` into `ControllerAppApp`

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/App/ControllerAppApp.swift`

- [ ] **Step 1: Rewrite app entry point**

Overwrite `controller-ios/ControllerApp/ControllerApp/App/ControllerAppApp.swift`:

```swift
import SwiftUI

@main
struct ControllerAppApp: App {
    @StateObject private var health = HealthStore()
    private let audioKeeper = BackgroundAudioKeeper()

    init() {
        audioKeeper.start()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(health)
                .task { await health.writer.requestAuthorization() }
        }
    }
}
```

- [ ] **Step 2: Build**
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 3: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/App/ControllerAppApp.swift
git commit -m "feat(controller-ios): wire HealthStore + BackgroundAudioKeeper into app entry"
```

---

## Task 12: Repurpose `StepCompanionsPanel` as "This Device" row

**Files:**
- Modify: `controller-ios/ControllerApp/ControllerApp/Views/StepCompanionsPanel.swift`

- [ ] **Step 1: Replace contents**

Overwrite `controller-ios/ControllerApp/ControllerApp/Views/StepCompanionsPanel.swift`:

```swift
import SwiftUI

struct StepCompanionsPanel: View {
    @EnvironmentObject var health: HealthStore

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "iphone.gen3")
            VStack(alignment: .leading, spacing: 2) {
                Text("This Device").font(.subheadline).bold()
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text("\(health.sessionSteps) steps")
                .font(.caption).monospacedDigit()
        }
        .padding(10)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }

    private var subtitle: String {
        if !health.writer.authorized { return "HealthKit not granted" }
        return health.enabled ? "Writes enabled" : "Writes off"
    }
}
```

Note: this view now depends on `HealthStore` via `@EnvironmentObject`. `MapTabView` already inherits the environment object from `RootView`, so no further wiring needed.

- [ ] **Step 2: Build**
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 3: Commit**

```bash
git add controller-ios/ControllerApp/ControllerApp/Views/StepCompanionsPanel.swift
git commit -m "feat(controller-ios): repurpose StepCompanionsPanel as This Device row"
```

---

## Task 13: Run full test suite

**Files:** none modified.

- [ ] **Step 1: Run all tests**

```bash
xcodebuild -project controller-ios/ControllerApp/ControllerApp.xcodeproj \
  -scheme ControllerApp \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  test
```

Expected: all existing tests (`BackendClientTests`, `LiveStatusSubscriberTests`, `SessionStoreTests`, `StatusSnapshotDecodingTests`) and new ones (`StepEventDecodingTests`, `StepClientURLBuildingTests`, `HealthStoreTests`) pass.

> **Note:** if the iPhone 17 simulator is not available locally, substitute any installed simulator (`xcrun simctl list devices available`). If `xcodebuild test` wedges (known issue per project memory), kill it and use the build-only command from Task 1 plus manual on-device verification.

- [ ] **Step 2: If anything fails**, fix the offending task before proceeding. Do not skip.

---

## Task 14: Manual on-device verification

**Files:** `controller-ios/docs/phase-1-verification.md` (already exists) — extend with HealthKit checks.

- [ ] **Step 1: Append HealthKit checklist to the existing Phase 1 doc**

Append to `controller-ios/docs/phase-1-verification.md`:

```markdown
## Phase 1.5 — HealthKit merge verification

- [ ] Fresh install → app prompts for HealthKit auth on first launch (HealthTabView "Request" button if denied initially).
- [ ] Toggle "Write steps to HealthKit" → row shows "Writes enabled".
- [ ] Start a session from the Map tab → step counter on Health tab increments live.
- [ ] Open iOS Health app → Steps source list shows TrailController writing samples.
- [ ] Background the app (home gesture) → after 2 minutes, return to app; counters should still be increasing (BackgroundAudioKeeper).
- [ ] Lock the phone → step events keep flowing (verify in Health app source data).
- [ ] Change backend URL in Settings → /ws/live and /ws/steps both reconnect; counters continue.
- [ ] Toggle off → /ws/steps disconnects, session counters reset to 0, cumulative persists.
```

- [ ] **Step 2: Run through the checklist on a real iPhone**. (Manual.)

- [ ] **Step 3: Commit**

```bash
git add controller-ios/docs/phase-1-verification.md
git commit -m "docs(controller-ios): add HealthKit merge verification checklist"
```

---

## Task 15: Retire `companion-ios/`

**Files:**
- Delete: entire `companion-ios/` directory.
- Modify: top-level `README.md` (remove StepCompanion references; mention HealthKit lives in TrailController now).
- Modify: `controller-ios/README.md` (add a "HealthKit" section pointing at HealthTabView).

- [ ] **Step 1: Update top-level README**

In `/Users/jl26/habitDevs/trail-simulator/README.md`, locate any reference to "StepCompanion" or `companion-ios` and replace with a note that step-to-HealthKit writing is built into the merged TrailController app. (Exact lines depend on current README state — do a `git grep -n "companion-ios\|StepCompanion"` and edit each match.)

- [ ] **Step 2: Update controller-ios README**

In `/Users/jl26/habitDevs/trail-simulator/controller-ios/README.md`, add a new section after the existing "Connect to trail-simulator" section:

```markdown
## 7. HealthKit (built-in)

The Health tab handles step-to-HealthKit writing on this device:
- First launch prompts for HealthKit write permission.
- "Write steps to HealthKit" toggle controls the `/ws/steps` subscription.
- Session and cumulative counters track what's been written.

HealthKit requires a paid Apple Developer Program membership to enable on a sideloaded build. Free Apple IDs cannot ship HealthKit.
```

- [ ] **Step 3: Delete the companion-ios folder**

```bash
git rm -r companion-ios/
```

- [ ] **Step 4: Verify build still passes**

Run the xcodebuild build command from Task 1 Step 3.
Expected: `BUILD SUCCEEDED`.

- [ ] **Step 5: Commit**

```bash
git add README.md controller-ios/README.md
git commit -m "chore: retire companion-ios after merge into ControllerApp"
```

---

## Self-Review Notes

Spec coverage check:
- §3 architecture → Tasks 3-12 cover Health/ files, TabView, repurposed panel.
- §4.1 ported files → Tasks 3, 4, 6.
- §4.2 new views → Tasks 8, 9.
- §4.3 repurposed panel → Task 12.
- §4.4 HealthStore → Task 7.
- §5 data flow → wired in Tasks 10, 11.
- §6 UI nav → Task 10.
- §7 lifecycle → Tasks 2, 3, 11.
- §8 capabilities → Tasks 1, 2.
- §9 persistence → Task 7 (UserDefaults keys covered + tested).
- §10 testing → Tasks 5, 6, 7, 13.
- §11 migration → Tasks 14, 15.

Type consistency check passes (`HealthStore.connect(baseURL:label:)`, `StepClient.stepsURL(from:)`, `StepEvent` shape used identically across tasks).
