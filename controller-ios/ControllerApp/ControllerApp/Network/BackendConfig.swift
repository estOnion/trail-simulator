import Foundation

struct BackendConfig: Equatable, Sendable {
    var baseURL: URL

    static let `default` = BackendConfig(baseURL: URL(string: "http://127.0.0.1:8787")!)

    static let storageKey = "BackendConfig.baseURL"

    static func loadFromUserDefaults(_ defaults: UserDefaults = .standard) -> BackendConfig {
        guard
            let raw = defaults.string(forKey: storageKey),
            let url = URL(string: raw)
        else { return .default }
        return BackendConfig(baseURL: url)
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(baseURL.absoluteString, forKey: Self.storageKey)
    }
}
