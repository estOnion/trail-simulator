# Controller-iOS Phase 1 — Final Senior Developer Review

**Date:** 2026-05-20
**Scope:** Whole of Phase 1, extra attention on Stage B (6 Views + app entry) and integration.
**Plan:** `docs/superpowers/plans/2026-05-18-ios-controller-app-phase-1.md` (Task 13)
**Stage A** (models, BackendClient, LiveStatusSubscriber, SessionStore) was approved earlier; re-spot-checked here.

## Verdict: APPROVE

Build-only verification: **PASS** (`** BUILD SUCCEEDED **`).
Command:
```
xcodebuild build -project controller-ios/ControllerApp/ControllerApp.xcodeproj -scheme ControllerApp -destination 'generic/platform=iOS Simulator'
```
This used a generic destination — no simulator boot. The long `xcodebuild test` invocation was deliberately NOT run (prior wedge risk). Unit suite was last green at 18/18; static review below confirms coverage is intact (no tests added by Task 11).

---

## Criterion-by-criterion

### 1. Files match plan intent (paths, types, function names)
PASS. Every Stage B file matches the plan verbatim:
- `Views/MapScreen.swift`, `Views/SearchBar.swift`, `Views/SessionControls.swift`, `Views/StepCompanionsPanel.swift`, `Views/RootView.swift` (incl. private `StatePill`), `Views/SettingsScreen.swift`, `App/ControllerAppApp.swift` (`@main` → `RootView`).
- Type/func names identical to plan. Stage A files match plan with the already-approved post-Stage-A refactor (explicit `CodingKeys`, `Sendable` conformances, bare `JSONDecoder()` instead of `.convertFromSnakeCase`).

### 2. File structure — no rogue/missed files, no scope creep
PASS. All 21 source files present at the nested `controller-ios/ControllerApp/ControllerApp/...` paths; `controller-ios/docs/api-contract.md` (Task 2) and `controller-ios/README.md` (Task 14) present. No extra source files. See non-blocking note on the deleted `ControllerApp_temp` scaffolding artifact.

### 3. Swift code quality
PASS.
- **Actors:** `BackendClient` and `LiveStatusSubscriber` are `actor`s; `SessionStore` is `@MainActor final class ObservableObject`. Models/`BackendConfig` carry `Sendable`. `BackendError`, `CooldownDetail`, `StatusSnapshot`, etc. are value types — safe to cross the actor boundary (e.g. `SessionControls.action` catching `BackendError` thrown from the actor).
- **`checkOk` error mapping** (`BackendClient.swift:88-113`) matches the API contract: 409 → `sessionAlreadyActive` when `isStart` else `sessionNotActive` (`isStart` set via `path.hasSuffix("/session")` at line 76); 429 → `cooldown(CooldownDetail)` via re-serialize + instance-decoder; 502 → `routing`; default → `server(code, detail)`. Tests `BackendClientTests` exercise 200/409-start/429/409-retarget/502/search.
- **Breadcrumb gating** (`SessionStore.swift:30,38`): uses the static `activeStates` set `{starting, running, paused}`, not inline duplication; `currentPosition` updates regardless of state, breadcrumb appends only in active states. Covered by `SessionStoreTests`.
- **Force-unwraps:** all confined to provably-safe URL construction (`BackendConfig` literal default, `URLComponents`/`comps.url!` in `BackendClient.search`, `webSocketURL`). Acceptable per plan.
- **RootView wiring:** `SearchBar`/`MapScreen`/`SessionControls`/`StepCompanionsPanel` composed with `.environmentObject(store)`; live stream consumed in `.task` and re-established on `.onChange(of: config)` (old stream finished via `subscriber.start()` → `cancel()`, so the prior `.task` loop terminates cleanly — no leaked consumer). `SettingsScreen` save persists config + `client.updateBaseURL`; `probe()` uses a throwaway `BackendClient`. Sound.

### 4. Latent issues already flagged for post-Phase-1 (recorded, not blocking)
- `/api/search` 502 is a geocoder error but is mapped to `.routing` (`BackendClient.swift:54` → `checkOk` 502 branch). Mislabel only; surfaced to user as "Search failed" anyway.
- `SearchResult.id` (`SearchResult.swift:9`) = `"lat,lon,displayName"` — collision risk for identical coord+name in a `ForEach`.
- `SessionState.unknown` (`SessionState.swift:7-10`) decodes any unrecognized state silently to `.unknown` (intended forward-compat; no telemetry).
- Pre-existing `ControllerAppUITests` target is broken — see Issue 1.

---

## Issues

### Issue 1 — `ControllerAppUITests` target references a non-existent synchronized folder (non-blocking)
**Where:** `controller-ios/ControllerApp/ControllerApp.xcodeproj/project.pbxproj:43-47` (PBXFileSystemSynchronizedRootGroup `path = ControllerAppUITests`) + native target `954542412...` lines 156-178.
**What:** The `ControllerAppUITests` synchronized root group points at a `ControllerAppUITests/` folder that does not exist on disk (`find`/`ls` return nothing). A `xcodebuild test` that builds all targets would fail building this UI-test bundle. Does NOT affect `xcodebuild build -scheme ControllerApp` (verified PASS) nor the `ControllerAppTests` unit bundle.
**Severity:** non-blocking (pre-existing; explicitly out of Phase 1 scope per the brief).
**Suggested fix (post-Phase-1):** Either delete the `ControllerAppUITests` target + its product/group references from the pbxproj, or create the on-disk folder with a stub `XCTestCase`. Until then, restrict test runs to the unit bundle (e.g. `-only-testing:ControllerAppTests`).

### Issue 2 — Deployment target is iOS 26.0, plan specified iOS 17.0 (non-blocking)
**Where:** `project.pbxproj:338,396` (`IPHONEOS_DEPLOYMENT_TARGET = 26.0`).
**What:** Plan and Info.plist messaging target iOS 17+; the project is set to 26.0. The code uses no APIs newer than iOS 17, so this only narrows the install base unnecessarily and contradicts plan/README intent.
**Severity:** non-blocking.
**Suggested fix:** Lower `IPHONEOS_DEPLOYMENT_TARGET` to `17.0` for app + test targets to match plan and README, unless 26.0 is an intentional device-fleet decision.

### Issue 3 — "Swift 6 strict concurrency" expectation vs. actual `SWIFT_VERSION = 5.0` (non-blocking / documentation)
**Where:** `project.pbxproj:434,467,...` (`SWIFT_VERSION = 5.0`) with `SWIFT_DEFAULT_ACTOR_ISOLATION = nonisolated` (`:431,464`).
**What:** The build compiles in Swift 5 language mode, so strict-concurrency diagnostics are warnings, not errors. The review brief described the app as "Swift 6 strict concurrency"; the project is not in Swift 6 mode. This is why passing the `BackendClient` actor into nonisolated SwiftUI Views compiles without isolation errors. The actor/`@MainActor`/`Sendable` design is nonetheless correct and would largely hold under Swift 6.
**Severity:** non-blocking (matches plan's stated "Swift 5.10+"; only the review framing said Swift 6).
**Suggested fix:** None required for Phase 1. If Swift 6 mode is desired later, flip `SWIFT_VERSION = 6.0` and resolve any resulting Sendable/isolation warnings (expected to be minimal given the current design).

### Issue 4 — Manual Info.plist portrait-only is overridden by generated orientation keys (non-blocking)
**Where:** App target has both `GENERATE_INFOPLIST_FILE = YES` and `INFOPLIST_FILE = ControllerApp/Resources/Info.plist`, plus `INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone = "...Portrait LandscapeLeft LandscapeRight"` (`project.pbxproj` Debug/Release app configs).
**What:** Build merges the `INFOPLIST_KEY_*` settings into the manual plist (build verified OK). The plan's intent was portrait-only (`Info.plist:16-19`), but the generated `INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone` re-enables landscape, taking precedence. Cosmetic — does not affect correctness.
**Severity:** non-blocking.
**Suggested fix:** If portrait-only is desired, set `INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone` to `UIInterfaceOrientationPortrait` (or remove the generated orientation keys and let the manual plist govern).

### Issue 5 — Unstaged housekeeping artifacts (non-blocking)
**Where:** Working tree: `D controller-ios/ControllerApp_temp/Resources/Info.plist` (the temp scaffolding dir is otherwise gone); untracked Xcode user state (`xcuserstate`, `IDEFindNavigatorScopes.plist`).
**What:** Leftover deletion from removed scaffolding plus user-local Xcode files. Not part of Phase 1 sources.
**Severity:** non-blocking.
**Suggested fix:** Commit the `ControllerApp_temp` deletion as cleanup; add `xcuserdata/` to `.gitignore`.

---

## Rationale

All Phase 1 source files match the plan's intent, paths, types, and function names. The actor/`@MainActor` architecture is correct, error mapping matches the API contract, breadcrumb gating uses the shared static set, and force-unwraps are confined to safe URL construction. RootView integration, the live WebSocket stream lifecycle, and the Settings save/probe path are all sound. The app target builds cleanly (authoritative build-only PASS) and the 18-test unit suite is statically intact. The five recorded issues are all non-blocking and most were pre-flagged for post-Phase-1. **APPROVE.**
