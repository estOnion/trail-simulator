# StepCompanion — Xcode Setup & Sideload Guide

StepCompanion connects to trail-simulator over LAN WebSocket and writes step count + walking distance to HealthKit on your iPhone. A free Apple ID is sufficient for sideloading.

## 1. Create the Xcode project

1. Open Xcode (15 or later).
2. **File → New → Project** → iOS → **App**.
3. Fill in:
   - **Product Name**: `StepCompanion`
   - **Bundle Identifier**: anything unique, e.g. `com.yourname.stepcompanion`
   - **Interface**: SwiftUI
   - **Language**: Swift
4. Choose a save location (e.g. `companion-ios/`), then click **Create**.

## 2. Replace the generated Swift files

Delete the placeholder Swift files Xcode created (`ContentView.swift`, `<AppName>App.swift`), then copy in the four files from this folder:

```
companion-ios/StepCompanion/StepCompanionApp.swift
companion-ios/StepCompanion/ContentView.swift
companion-ios/StepCompanion/HealthWriter.swift
companion-ios/StepCompanion/StepClient.swift
```

Drag them into the Xcode project navigator under the `StepCompanion` group.

## 3. Add HealthKit capability

1. Click the top-level project in the navigator → select the **StepCompanion** target.
2. **Signing & Capabilities** tab → **+ Capability** → search for **HealthKit** → double-click.

## 4. Set Info.plist keys

Xcode 13+ uses a privacy manifest instead of a standalone `Info.plist` in many templates. Either:

**Option A** — copy `companion-ios/StepCompanion/Info.plist` into the project (drag into navigator, check "Copy if needed"), then in Build Settings set **Info.plist File** to the copied file path.

**Option B** — add the keys directly via Xcode UI:
- Project → target → **Info** tab → add these keys:
  - `NSHealthShareUsageDescription` — `"This app reads health data to display authorization status."`
  - `NSHealthUpdateUsageDescription` — `"This app writes step count and walking distance received from trail-simulator to HealthKit."`
  - `NSLocalNetworkUsageDescription` — `"This app connects to trail-simulator on your local Wi-Fi network to receive step events."`

## 5. Signing

1. **Signing & Capabilities** → **Team** → pick your Apple ID (add one via Xcode → Settings → Accounts if needed).
2. Set a unique **Bundle Identifier** (e.g. `com.yourname.stepcompanion`).
3. Ensure **Automatically manage signing** is checked.

## 6. Sideload

1. Connect iPhone via USB. Trust the Mac on the phone if prompted.
2. Select your iPhone as the run destination in the toolbar.
3. Click **Run** (⌘R). Xcode builds and installs.
4. On the phone: **Settings → General → VPN & Device Management** → trust your developer certificate.
5. Open **StepCompanion** — it will ask for HealthKit permission. Grant **Steps** and **Walking + Running Distance** writes.

> **Note**: Free Apple ID sideloads expire after 7 days. Re-run from Xcode to refresh.

## 7. Connect to trail-simulator

1. Make sure trail-simulator is running with `--host 0.0.0.0` (or the machine's LAN IP):
   ```
   uv run trail_simulator --host 0.0.0.0 --port 8787
   ```
2. In StepCompanion, enter the Mac's LAN IP (e.g. `192.168.1.50`) and port `8787`.
3. Tap **Connect**. The backend status pill in the browser UI should show `step companion: connected`.
4. Enable step injection in trail-simulator's settings:
   ```python
   # trail_simulator/config.py — set temporarily for testing
   step_companion_enabled: bool = True
   ```

## 8. Verification protocol (Pikmin Bloom)

1. Note current step count in **Health app → Steps**.
2. Start a route in trail-simulator (e.g. 500 m loop).
3. Watch StepCompanion — "Steps written" should increment each tick.
4. After the route ends, open **Health app → Steps** and confirm the count increased.
5. Open Pikmin Bloom. Walk the same route again with the companion connected.
6. Check whether Pikmin Bloom's step/distance progress advances beyond what the GPS route alone would produce.

**Open question**: Pikmin Bloom may read live `CMPedometer` data instead of (or in addition to) HealthKit samples. If step progress does not advance in-game despite HealthKit writes succeeding, the HealthKit path is insufficient and motion coprocessor injection (requiring a jailbreak or TrollStore) would be needed.
