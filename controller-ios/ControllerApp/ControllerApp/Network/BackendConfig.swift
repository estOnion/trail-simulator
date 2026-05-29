import Foundation

struct BackendConfig: Equatable, Sendable {
    var baseURL: URL
    // Primary routing identity sent as X-Client-Id. Defaults to the device
    // name; the user can override it in Settings (persisted below).
    var clientId: String
    // Legacy fallback identity (X-Device-Name) kept for the web frontend /
    // single-device path.
    var deviceName: String?

    static let storageKey = "BackendConfig.baseURL"
    static let clientIdKey = "BackendConfig.clientId"
    static let deviceNameKey = "BackendConfig.deviceName"

    static func loadFromUserDefaults(
        _ defaults: UserDefaults = .standard,
        defaultClientId: String
    ) -> BackendConfig {
        let url = (defaults.string(forKey: storageKey)).flatMap(URL.init(string:))
            ?? URL(string: "http://127.0.0.1:8787")!
        let clientId = defaults.string(forKey: clientIdKey) ?? defaultClientId
        let name = defaults.string(forKey: deviceNameKey)
        return BackendConfig(baseURL: url, clientId: clientId, deviceName: name)
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(baseURL.absoluteString, forKey: Self.storageKey)
        defaults.set(clientId, forKey: Self.clientIdKey)
        if let deviceName {
            defaults.set(deviceName, forKey: Self.deviceNameKey)
        } else {
            defaults.removeObject(forKey: Self.deviceNameKey)
        }
    }
}
