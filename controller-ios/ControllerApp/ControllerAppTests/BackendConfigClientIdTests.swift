import XCTest
@testable import ControllerApp

final class BackendConfigClientIdTests: XCTestCase {
    private func freshDefaults() -> UserDefaults {
        let d = UserDefaults(suiteName: "BackendConfigClientIdTests")!
        d.removePersistentDomain(forName: "BackendConfigClientIdTests")
        return d
    }

    func testDefaultsToProvidedDeviceNameWhenUnset() {
        let d = freshDefaults()
        let cfg = BackendConfig.loadFromUserDefaults(d, defaultClientId: "Jack's iPhone")
        XCTAssertEqual(cfg.clientId, "Jack's iPhone")
    }

    func testPersistedCustomClientIdWins() {
        let d = freshDefaults()
        var cfg = BackendConfig.loadFromUserDefaults(d, defaultClientId: "iPhone")
        cfg.clientId = "custom-uuid-123"
        cfg.save(to: d)

        let reloaded = BackendConfig.loadFromUserDefaults(d, defaultClientId: "iPhone")
        XCTAssertEqual(reloaded.clientId, "custom-uuid-123")
    }
}
