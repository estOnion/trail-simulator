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
        XCTAssertEqual(LiveStatusSubscriber.webSocketURL(from: http, deviceName: nil).absoluteString, "ws://192.168.1.5:8787/ws/live")

        let https = URL(string: "https://example.com")!
        XCTAssertEqual(LiveStatusSubscriber.webSocketURL(from: https, deviceName: nil).absoluteString, "wss://example.com/ws/live")
    }

    func testWebSocketURLAppendsDeviceQueryParam() {
        let base = URL(string: "http://192.168.1.5:8080")!
        let url = LiveStatusSubscriber.webSocketURL(from: base, deviceName: "iPhone 15")
        XCTAssertEqual(url.absoluteString, "ws://192.168.1.5:8080/ws/live?device=iPhone%2015")
    }

    func testWebSocketURLNilDeviceOmitsQueryParam() {
        let base = URL(string: "http://192.168.1.5:8080")!
        let url = LiveStatusSubscriber.webSocketURL(from: base, deviceName: nil)
        XCTAssertNil(url.query)
    }
}
