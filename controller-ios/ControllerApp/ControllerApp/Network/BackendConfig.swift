import Foundation

struct BackendConfig: Equatable, Sendable {
    var baseURL: URL
    // The backend's registered DeviceName for this iPhone, chosen by the user
    // from /api/devices. iOS 16+ no longer exposes the user-assigned device
    // name via UIDevice.current.name (it returns a generic "iPhone"), so the
    // app cannot derive this itself — it must come from the backend registry.
    var deviceName: String?

    static let `default` = BackendConfig(baseURL: URL(string: "http://127.0.0.1:8787")!, deviceName: nil)

    static let storageKey = "BackendConfig.baseURL"
    static let deviceNameKey = "BackendConfig.deviceName"

    static func loadFromUserDefaults(_ defaults: UserDefaults = .standard) -> BackendConfig {
        guard
            let raw = defaults.string(forKey: storageKey),
            let url = URL(string: raw)
        else { return .default }
        let name = defaults.string(forKey: deviceNameKey)
        return BackendConfig(baseURL: url, deviceName: name)
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(baseURL.absoluteString, forKey: Self.storageKey)
        if let deviceName {
            defaults.set(deviceName, forKey: Self.deviceNameKey)
        } else {
            defaults.removeObject(forKey: Self.deviceNameKey)
        }
    }
}
