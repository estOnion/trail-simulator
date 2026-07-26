import Network
import XCTest
@testable import ControllerApp

/// Feature-level cover for the live subscriber against a real WebSocket on
/// loopback: it must announce `.connected` once the socket is actually up,
/// forward decoded snapshots, and announce `.disconnected` when the peer goes
/// away. Those edges are what drives the Settings tab badge.
final class LiveStatusSubscriberStreamTests: XCTestCase {

    private static let frame = #"{"state":"running","session_id":7,"current_lat":35.0,"current_lon":139.0,"target_lat":35.1,"target_lon":139.1,"speed_kmh":4,"progress_m":10,"total_m":100,"last_error":null,"cooldown_remaining_s":0,"steps_sent":5,"step_companions":[]}"#

    private func baseURL(port: UInt16) -> URL {
        URL(string: "http://127.0.0.1:\(port)")!
    }

    func testAnnouncesConnectedThenForwardsSnapshot() async throws {
        let server = try TinyWebSocketServer()
        defer { server.stop() }
        server.onConnect = { $0.sendText(Self.frame) }
        let subscriber = LiveStatusSubscriber()
        defer { Task { await subscriber.cancel() } }

        let stream = await subscriber.start(baseURL: baseURL(port: server.port), clientId: nil)
        var seen: [LiveEvent] = []
        for await event in stream {
            seen.append(event)
            if case .snapshot = event { break }
        }

        guard seen.count >= 2, case .connected = seen[0] else {
            return XCTFail("expected .connected first, got \(seen)")
        }
        guard case .snapshot(let snap) = seen[1] else {
            return XCTFail("expected a snapshot second, got \(seen)")
        }
        XCTAssertEqual(snap.sessionId, 7)
        XCTAssertEqual(snap.state, .running)
    }

    func testAnnouncesDisconnectedWhenThePeerHangsUp() async throws {
        let server = try TinyWebSocketServer()
        defer { server.stop() }
        // Say hello so the subscriber reaches .connected, then drop the socket.
        server.onConnect = { peer in
            peer.sendText(Self.frame)
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.2) { peer.close() }
        }
        let subscriber = LiveStatusSubscriber()
        defer { Task { await subscriber.cancel() } }

        let stream = await subscriber.start(baseURL: baseURL(port: server.port), clientId: nil)
        var sawConnected = false
        var sawDisconnected = false
        for await event in stream {
            switch event {
            case .connected: sawConnected = true
            case .disconnected: sawDisconnected = true
            case .snapshot: break
            }
            if sawDisconnected { break }
        }

        XCTAssertTrue(sawConnected, "should have reported the socket coming up")
        XCTAssertTrue(sawDisconnected, "should have reported the drop")
    }

    func testUndecodableFrameIsSkippedButKeepsTheConnection() async throws {
        let server = try TinyWebSocketServer()
        defer { server.stop() }
        server.onConnect = { peer in
            peer.sendText("not json")
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.1) {
                peer.sendText(Self.frame)
            }
        }
        let subscriber = LiveStatusSubscriber()
        defer { Task { await subscriber.cancel() } }

        let stream = await subscriber.start(baseURL: baseURL(port: server.port), clientId: nil)
        var seen: [LiveEvent] = []
        for await event in stream {
            seen.append(event)
            if case .snapshot = event { break }
        }

        // Garbage yields no event of its own — connected, then the good frame.
        XCTAssertEqual(seen.count, 2, "garbage should not surface as an event: \(seen)")
        if case .disconnected = seen[1] { XCTFail("garbage must not drop the connection") }
    }

    func testNoConnectedEventWhenNothingIsListening() async throws {
        // Reserve a port, then release it so the connection is refused.
        let dead = try TinyWebSocketServer()
        let port = dead.port
        dead.stop()
        let subscriber = LiveStatusSubscriber()

        let stream = await subscriber.start(baseURL: baseURL(port: port), clientId: nil)
        var first: LiveEvent?
        for await event in stream {
            first = event
            break  // the first event decides it: a failed dial can't be .connected
        }
        await subscriber.cancel()

        guard let first else { return }  // stream ended without emitting: also fine
        if case .connected = first {
            XCTFail("reported connected with no server listening")
        }
    }
}

// MARK: - Loopback WebSocket server

/// Minimal Network.framework WebSocket server used only by these tests.
final class TinyWebSocketServer {
    /// A single accepted client, exposed so a test can script what the peer does.
    final class Peer {
        private let connection: NWConnection
        init(_ connection: NWConnection) { self.connection = connection }

        func sendText(_ text: String) {
            let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
            let context = NWConnection.ContentContext(identifier: "text", metadata: [metadata])
            connection.send(content: Data(text.utf8), contentContext: context,
                            isComplete: true, completion: .contentProcessed { _ in })
        }

        func close() { connection.cancel() }
    }

    private let listener: NWListener
    private let queue = DispatchQueue(label: "tiny-ws-server")
    private var peers: [Peer] = []

    /// Called on the server queue for each accepted client.
    var onConnect: ((Peer) -> Void)?

    init() throws {
        let options = NWProtocolWebSocket.Options()
        options.autoReplyPing = true
        let parameters = NWParameters.tcp
        parameters.allowLocalEndpointReuse = true
        parameters.defaultProtocolStack.applicationProtocols.insert(options, at: 0)

        listener = try NWListener(using: parameters, on: .any)
        let ready = DispatchSemaphore(value: 0)
        listener.stateUpdateHandler = { state in
            if case .ready = state { ready.signal() }
            if case .failed = state { ready.signal() }
        }
        listener.newConnectionHandler = { [weak self] connection in
            guard let self else { return }
            connection.start(queue: self.queue)
            let peer = Peer(connection)
            self.peers.append(peer)
            // Drain inbound frames so the connection stays healthy.
            self.receiveLoop(connection)
            self.onConnect?(peer)
        }
        listener.start(queue: queue)
        guard ready.wait(timeout: .now() + 5) == .success, listener.port != nil else {
            throw XCTSkip("could not open a loopback WebSocket listener")
        }
    }

    var port: UInt16 { listener.port!.rawValue }

    func stop() {
        peers.forEach { $0.close() }
        peers.removeAll()
        listener.cancel()
    }

    private func receiveLoop(_ connection: NWConnection) {
        connection.receiveMessage { [weak self] _, _, isComplete, error in
            guard error == nil, isComplete else { return }
            self?.receiveLoop(connection)
        }
    }
}
