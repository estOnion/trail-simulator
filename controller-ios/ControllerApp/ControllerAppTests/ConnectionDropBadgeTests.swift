import XCTest
@testable import ControllerApp

/// The Settings tab badge exists to tell the user about a dropped connection
/// they can't currently see. These pin when it appears and when it clears.
@MainActor
final class ConnectionDropBadgeTests: XCTestCase {

    func testNoBadgeBeforeAnythingHappens() {
        XCTAssertFalse(SessionStore().settingsUnread)
    }

    func testDropOnAnotherTabRaisesTheBadge() {
        let store = SessionStore()

        store.noteConnectionDropped(viewingSettings: false)

        XCTAssertTrue(store.settingsUnread)
    }

    func testDropWhileOnSettingsDoesNotBadge() {
        // The user is already looking at the connection state — badging it
        // would flag something they can see.
        let store = SessionStore()

        store.noteConnectionDropped(viewingSettings: true)

        XCTAssertFalse(store.settingsUnread)
    }

    func testOpeningSettingsClearsTheBadge() {
        let store = SessionStore()
        store.noteConnectionDropped(viewingSettings: false)

        store.markSettingsSeen()

        XCTAssertFalse(store.settingsUnread)
    }

    func testRepeatedDropsStayASingleUnreadFlag() {
        let store = SessionStore()

        store.noteConnectionDropped(viewingSettings: false)
        store.noteConnectionDropped(viewingSettings: false)

        XCTAssertTrue(store.settingsUnread)
        store.markSettingsSeen()
        XCTAssertFalse(store.settingsUnread, "one visit clears every prior drop")
    }

    func testDropAfterClearingBadgesAgain() {
        let store = SessionStore()
        store.noteConnectionDropped(viewingSettings: false)
        store.markSettingsSeen()

        store.noteConnectionDropped(viewingSettings: false)

        XCTAssertTrue(store.settingsUnread)
    }
}
