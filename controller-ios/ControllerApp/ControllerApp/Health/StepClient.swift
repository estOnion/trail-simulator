import Foundation
import Combine
import UIKit

@MainActor
final class StepClient: ObservableObject {
    @Published var connected = false
    @Published var lastError: String?

    private var task: URLSessionWebSocketTask?
    private var onEvent: ((StepEvent) -> Void)?

    nonisolated static func stepsURL(from base: URL) -> URL? {
        var comps = URLComponents(url: base, resolvingAgainstBaseURL: false)
        guard let scheme = comps?.scheme?.lowercased() else { return nil }
        switch scheme {
        case "http":  comps?.scheme = "ws"
        case "https": comps?.scheme = "wss"
        case "ws", "wss": break
        default: return nil
        }
        comps?.path = "/ws/steps"
        return comps?.url
    }

    func connect(baseURL: URL, label: String, onEvent: @escaping (StepEvent) -> Void) {
        guard let url = Self.stepsURL(from: baseURL) else {
            lastError = "invalid base URL"
            return
        }
        self.onEvent = onEvent
        task?.cancel(with: .normalClosure, reason: nil)
        let session = URLSession(configuration: .default)
        task = session.webSocketTask(with: url)
        task?.resume()

        Task { @MainActor in
            let hello: [String: String] = ["type": "hello", "device_label": label, "udid": ""]
            if let data = try? JSONSerialization.data(withJSONObject: hello),
               let text = String(data: data, encoding: .utf8) {
                try? await task?.send(.string(text))
            }
            connected = true
            receive()
            scheduleHeartbeat()
        }
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
                    if case .string(let text) = msg, let data = text.data(using: .utf8),
                       let event = try? JSONDecoder().decode(StepEvent.self, from: data) {
                        self.onEvent?(event)
                    }
                    self.receive()
                }
            }
        }
    }

    private func scheduleHeartbeat() {
        Task { @MainActor in
            while connected {
                try? await Task.sleep(for: .seconds(10))
                guard connected else { break }
                let payload = "{\"type\":\"heartbeat\"}"
                try? await task?.send(.string(payload))
            }
        }
    }
}
