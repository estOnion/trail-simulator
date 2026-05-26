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
