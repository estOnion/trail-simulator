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
