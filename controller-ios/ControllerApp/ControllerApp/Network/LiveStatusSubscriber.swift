import Foundation

/// Events emitted by the live subscriber: status updates plus connection
/// transitions so the UI can reflect real reachability (e.g. a tab badge).
enum LiveEvent {
    case snapshot(StatusSnapshot)
    case connected
    case disconnected
}

/// Subscribes to `/ws/live` and yields `LiveEvent`s as an AsyncStream.
/// Reconnects on transport errors with capped exponential backoff until cancelled.
actor LiveStatusSubscriber {
    private var task: URLSessionWebSocketTask?
    private var continuation: AsyncStream<LiveEvent>.Continuation?
    private var consumerTask: Task<Void, Never>?

    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    /// Starts the subscription. Calling again replaces the existing one.
    func start(baseURL: URL, clientId: String?) -> AsyncStream<LiveEvent> {
        cancel()

        let wsURL = Self.webSocketURL(from: baseURL, clientId: clientId)
        let (stream, cont) = AsyncStream<LiveEvent>.makeStream()
        continuation = cont

        consumerTask = Task { [session, weak self] in
            var backoff: UInt64 = 1_000_000_000 // 1s in ns
            let cap: UInt64    = 10_000_000_000 // 10s

            while !Task.isCancelled {
                let task = session.webSocketTask(with: wsURL)
                await self?.setTask(task)
                task.resume()

                // The first successful receive proves the socket is up; a thrown
                // receive means the connection dropped. Announce each transition
                // once per cycle so the UI sees connected/disconnected edges.
                var announcedConnected = false
                do {
                    while !Task.isCancelled {
                        let msg = try await task.receive()
                        if !announcedConnected {
                            announcedConnected = true
                            cont.yield(.connected)
                        }
                        switch msg {
                        case .string(let text):
                            if let snap = try? Self.decodeFrame(text) {
                                cont.yield(.snapshot(snap))
                            }
                        case .data(let data):
                            if let text = String(data: data, encoding: .utf8),
                               let snap = try? Self.decodeFrame(text) {
                                cont.yield(.snapshot(snap))
                            }
                        @unknown default:
                            break
                        }
                    }
                } catch {
                    // fall through to backoff
                }

                task.cancel(with: .normalClosure, reason: nil)
                if Task.isCancelled { break }

                cont.yield(.disconnected)
                try? await Task.sleep(nanoseconds: backoff)
                backoff = min(backoff * 2, cap)
            }
            cont.finish()
        }

        return stream
    }

    func cancel() {
        consumerTask?.cancel()
        consumerTask = nil
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        continuation?.finish()
        continuation = nil
    }

    private func setTask(_ t: URLSessionWebSocketTask) {
        task = t
    }

    /// Static helpers — kept static so they're testable without spinning up a real task.
    static func decodeFrame(_ text: String) throws -> StatusSnapshot {
        guard let data = text.data(using: .utf8) else {
            throw BackendError.transport("non-utf8 frame")
        }
        return try JSONDecoder().decode(StatusSnapshot.self, from: data)
    }

    static func webSocketURL(from baseURL: URL, clientId: String?) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        components.scheme = (baseURL.scheme == "https") ? "wss" : "ws"
        components.path = "/ws/live"
        if let clientId {
            components.queryItems = [URLQueryItem(name: "client", value: clientId)]
        } else {
            components.query = nil
        }
        return components.url!
    }
}
