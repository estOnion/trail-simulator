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

    func testRetargetMaps409ToSessionNotActive() async {
        let body = #"{"detail":"no active session"}"#.data(using: .utf8)!
        let client = makeClient { req in
            (HTTPURLResponse(url: req.url!, statusCode: 409, httpVersion: nil, headerFields: nil)!, body)
        }
        let req = RetargetRequest(destinations: [.init(lat: 1, lon: 1)], loop: nil)
        do {
            _ = try await client.retarget(req)
            XCTFail("expected throw")
        } catch BackendError.sessionNotActive(let msg) {
            XCTAssertEqual(msg, "no active session")
        } catch { XCTFail("wrong error: \(error)") }
    }

    func testRetargetMaps502ToRouting() async {
        let body = #"{"detail":"OSRM unreachable"}"#.data(using: .utf8)!
        let client = makeClient { req in
            (HTTPURLResponse(url: req.url!, statusCode: 502, httpVersion: nil, headerFields: nil)!, body)
        }
        let req = RetargetRequest(destinations: [.init(lat: 1, lon: 1)], loop: nil)
        do {
            _ = try await client.retarget(req)
            XCTFail("expected throw")
        } catch BackendError.routing(let msg) {
            XCTAssertEqual(msg, "OSRM unreachable")
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
