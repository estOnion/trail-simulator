import XCTest
@testable import ControllerApp

final class StatusSnapshotDecodingTests: XCTestCase {
    private let decoder = JSONDecoder()

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
