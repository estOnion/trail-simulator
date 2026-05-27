import XCTest
@testable import ControllerApp

final class BackendClientHeaderTests: XCTestCase {

    final class HeaderRecordingURLProtocol: URLProtocol {
        nonisolated(unsafe) static var lastRequest: URLRequest?

        override class func canInit(with request: URLRequest) -> Bool { true }
        override class func canonicalRequest(for r: URLRequest) -> URLRequest { r }

        override func startLoading() {
            Self.lastRequest = request
            let resp = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let data = "{}".data(using: .utf8)!
            client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        }

        override func stopLoading() {}
    }

    private func makeClient(deviceName: String?) -> BackendClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HeaderRecordingURLProtocol.self]
        let session = URLSession(configuration: config)
        let url = URL(string: "http://localhost:8080")!
        return BackendClient(baseURL: url, deviceName: deviceName, session: session)
    }

    func testGetRequestStampsDeviceNameHeader() async throws {
        let client = makeClient(deviceName: "Jack iPhone")
        // fetchStatus hits GET /api/status via getJSON
        _ = try? await client.fetchStatus()
        XCTAssertEqual(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"), "Jack iPhone")
    }

    func testPostJSONStampsDeviceNameHeader() async throws {
        let client = makeClient(deviceName: "Jack iPhone")
        // setSpeed hits POST /api/speed via postJSON
        _ = try? await client.setSpeed(5.0)
        XCTAssertEqual(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"), "Jack iPhone")
    }

    func testPostEmptyStampsDeviceNameHeader() async throws {
        let client = makeClient(deviceName: "Jack iPhone")
        _ = try? await client.pause()
        XCTAssertEqual(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"), "Jack iPhone")
    }

    func testSearchStampsDeviceNameHeader() async throws {
        let client = makeClient(deviceName: "Jack iPhone")
        _ = try? await client.search(query: "trail")
        XCTAssertEqual(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"), "Jack iPhone")
    }

    func testNoHeaderWhenDeviceNameIsNil() async throws {
        let client = makeClient(deviceName: nil)
        _ = try? await client.fetchStatus()
        XCTAssertNil(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"))
    }

    func testUpdateDeviceNameAppliesOnNextRequest() async throws {
        let client = makeClient(deviceName: nil)
        _ = try? await client.fetchStatus()
        XCTAssertNil(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"))

        await client.updateDeviceName("Jack iPhone")
        _ = try? await client.fetchStatus()
        XCTAssertEqual(HeaderRecordingURLProtocol.lastRequest?.value(forHTTPHeaderField: "X-Device-Name"), "Jack iPhone")
    }
}
