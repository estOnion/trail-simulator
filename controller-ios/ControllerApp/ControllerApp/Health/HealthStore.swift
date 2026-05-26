import Foundation
import Combine

@MainActor
final class HealthStore: ObservableObject {
    @Published var enabled: Bool {
        didSet {
            defaults.set(enabled, forKey: Keys.enabled)
            if enabled != oldValue {
                sessionSteps = 0
                sessionDistanceM = 0
            }
        }
    }
    @Published private(set) var sessionSteps: Int = 0
    @Published private(set) var sessionDistanceM: Double = 0
    @Published private(set) var cumulativeSteps: Int
    @Published private(set) var cumulativeDistanceM: Double

    let writer: HealthWriter
    let client: StepClient

    private let defaults: UserDefaults

    private enum Keys {
        static let enabled = "health.enabled"
        static let cumulativeSteps = "health.cumulativeSteps"
        static let cumulativeDistanceM = "health.cumulativeDistanceM"
    }

    init(defaults: UserDefaults = .standard,
         writer: HealthWriter? = nil,
         client: StepClient? = nil) {
        self.defaults = defaults
        self.writer = writer ?? HealthWriter()
        self.client = client ?? StepClient()
        self.enabled = defaults.object(forKey: Keys.enabled) as? Bool ?? true
        self.cumulativeSteps = defaults.integer(forKey: Keys.cumulativeSteps)
        self.cumulativeDistanceM = defaults.double(forKey: Keys.cumulativeDistanceM)
    }

    func apply(event: StepEvent) {
        guard event.type == "steps",
              let n = event.steps, n > 0,
              let dist = event.distance_m else { return }
        sessionSteps += n
        sessionDistanceM += dist
        cumulativeSteps += n
        cumulativeDistanceM += dist
        defaults.set(cumulativeSteps, forKey: Keys.cumulativeSteps)
        defaults.set(cumulativeDistanceM, forKey: Keys.cumulativeDistanceM)
        if enabled && writer.authorized {
            Task { await writer.writeSteps(count: n, distanceMeters: dist, end: Date()) }
        }
    }

    func connect(baseURL: URL, label: String) {
        guard enabled, writer.authorized else { return }
        client.connect(baseURL: baseURL, label: label) { [weak self] event in
            Task { @MainActor [weak self] in self?.apply(event: event) }
        }
    }

    func disconnect() {
        client.disconnect()
    }

    func reconnect(baseURL: URL, label: String) {
        disconnect()
        connect(baseURL: baseURL, label: label)
    }
}
