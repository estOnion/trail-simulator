import XCTest
@testable import ControllerApp

final class SessionControlsGatingTests: XCTestCase {

    private let allStates: [SessionState] = [
        .idle, .starting, .running, .paused, .stopping,
        .reconnecting, .error, .following, .unknown,
    ]

    // MARK: Walk (IOS-09)

    func testWalkEnabledOnlyForIdleAndError() {
        for state in allStates {
            let expected = (state == .idle || state == .error)
            XCTAssertEqual(
                state.canStartWalk(pinStage: .ready, inFlight: false), expected,
                "Walk enabled for \(state)")
        }
    }

    func testWalkDisabledWithoutOriginOrDestination() {
        for state in [SessionState.idle, .error] {
            XCTAssertFalse(state.canStartWalk(pinStage: .origin, inFlight: false), "\(state) no origin")
            XCTAssertFalse(state.canStartWalk(pinStage: .destination, inFlight: false), "\(state) no destination")
        }
    }

    func testWalkDisabledWhileRequestInFlight() {
        for state in [SessionState.idle, .error] {
            XCTAssertFalse(state.canStartWalk(pinStage: .ready, inFlight: true), "\(state) in flight")
        }
    }

    // MARK: Pause / Resume / Stop (IOS-10)

    func testPauseOnlyWhileRunning() {
        for state in allStates {
            XCTAssertEqual(state.showsPause, state == .running, "Pause for \(state)")
        }
    }

    func testResumeOnlyWhilePaused() {
        for state in allStates {
            XCTAssertEqual(state.showsResume, state == .paused, "Resume for \(state)")
        }
    }

    func testStopShownForActiveAndErrorStates() {
        let shown: Set<SessionState> = [.starting, .running, .paused, .reconnecting, .error]
        for state in allStates {
            XCTAssertEqual(state.showsStop, shown.contains(state), "Stop for \(state)")
        }
    }

    // MARK: Reset GPS (IOS-10)

    func testResetGPSIdleNeedsPosition() {
        XCTAssertTrue(SessionState.idle.showsResetGPS(hasPosition: true))
        XCTAssertFalse(SessionState.idle.showsResetGPS(hasPosition: false))
    }

    func testResetGPSInErrorWithOrWithoutPosition() {
        XCTAssertTrue(SessionState.error.showsResetGPS(hasPosition: true))
        XCTAssertTrue(SessionState.error.showsResetGPS(hasPosition: false))
    }

    func testResetGPSNeverInOtherStates() {
        for state in allStates where state != .idle && state != .error {
            XCTAssertFalse(state.showsResetGPS(hasPosition: true), "Reset for \(state) with position")
            XCTAssertFalse(state.showsResetGPS(hasPosition: false), "Reset for \(state) without position")
        }
    }
}
