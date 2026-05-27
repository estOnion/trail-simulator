import Foundation

/// Subscribes to `/ws/live` and yields `StatusSnapshot` updates as an AsyncStream.
/// Reconnects on transport errors with capped exponential backoff until cancelled.
actor LiveStatusSubscriber {
    private var task: URLSessionWebSocketTask?
    private var continuation: AsyncStream<StatusSnapshot>.Continuation?
    private var consumerTask: Task<Void, Never>?

    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    /// Starts the subscription. Calling again replaces the existing one.
    func start(baseURL: URL, deviceName: String?) -> AsyncStream<StatusSnapshot> {
        cancel()

        let wsURL = Self.webSocketURL(from: baseURL, deviceName: deviceName)
        let (stream, cont) = AsyncStream<StatusSnapshot>.makeStream()
        continuation = cont

        consumerTask = Task { [session, weak self] in
            var backoff: UInt64 = 1_000_000_000 // 1s in ns
            let cap: UInt64    = 10_000_000_000 // 10s

            while !Task.isCancelled {
                let task = session.webSocketTask(with: wsURL)
                await self?.setTask(task)
                task.resume()

                do {
                    while !Task.isCancelled {
                        let msg = try await task.receive()
                        switch msg {
                        case .string(let text):
                            if let snap = try? Self.decodeFrame(text) {
                                cont.yield(snap)
                            }
                        case .data(let data):
                            if let text = String(data: data, encoding: .utf8),
                               let snap = try? Self.decodeFrame(text) {
                                cont.yield(snap)
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

    static func webSocketURL(from baseURL: URL, deviceName: String?) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        components.scheme = (baseURL.scheme == "https") ? "wss" : "ws"
        components.path = "/ws/live"
        if let name = deviceName {
            components.queryItems = [URLQueryItem(name: "device", value: name)]
        } else {
            components.query = nil
        }
        return components.url!
    }
}
