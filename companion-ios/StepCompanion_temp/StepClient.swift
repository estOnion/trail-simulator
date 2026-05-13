import Foundation

// Message shapes from trail-simulator backend.
struct StepEvent: Decodable {
    let type: String
    let steps: Int?
    let distance_m: Double?
    let ts: String?
}

@MainActor
final class StepClient: ObservableObject {
    @Published var connected = false
    @Published var totalWritten = 0
    @Published var lastError: String?

    private var task: URLSessionWebSocketTask?
    private weak var writer: HealthWriter?

    func connect(url: URL, writer: HealthWriter) {
        self.writer = writer
        task?.cancel(with: .normalClosure, reason: nil)
        let session = URLSession(configuration: .default)
        task = session.webSocketTask(with: url)
        task?.resume()
        connected = true
        receive()
        scheduleHeartbeat()
    }

    func disconnect() {
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        connected = false
    }

    private func receive() {
        task?.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch result {
                case .failure(let error):
                    self.lastError = error.localizedDescription
                    self.connected = false
                case .success(let msg):
                    if case .string(let text) = msg {
                        self.handle(text)
                    }
                    self.receive()
                }
            }
        }
    }

    private func handle(_ text: String) {
        guard
            let data = text.data(using: .utf8),
            let event = try? JSONDecoder().decode(StepEvent.self, from: data),
            event.type == "steps",
            let n = event.steps, n > 0,
            let dist = event.distance_m
        else { return }

        Task {
            await writer?.writeSteps(count: n, distanceMeters: dist, end: Date())
            await MainActor.run { self.totalWritten += n }
        }
    }

    private func scheduleHeartbeat() {
        Task {
            while connected {
                try? await Task.sleep(for: .seconds(10))
                guard connected else { break }
                let payload = "{\"type\":\"heartbeat\",\"total_written\":\(totalWritten)}"
                try? await task?.send(.string(payload))
            }
        }
    }
}
