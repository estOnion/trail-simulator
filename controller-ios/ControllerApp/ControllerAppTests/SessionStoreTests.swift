import XCTest
import CoreLocation
@testable import ControllerApp

@MainActor
final class SessionStoreTests: XCTestCase {

    func snapshot(state: SessionState, lat: Double? = nil, lon: Double? = nil) -> StatusSnapshot {
        StatusSnapshot(state: state, sessionId: nil,
                       currentLat: lat, currentLon: lon,
                       targetLat: nil, targetLon: nil,
                       speedKmh: 0, progressM: 0, totalM: 0,
                       lastError: nil, cooldownRemainingS: 0,
                       stepsSent: 0, stepCompanions: [])
    }

    func testBreadcrumbAccumulatesOnlyInActiveStates() {
        let store = SessionStore()

        store.apply(snapshot: snapshot(state: .running, lat: 1, lon: 1))
        store.apply(snapshot: snapshot(state: .running, lat: 2, lon: 2))
        store.apply(snapshot: snapshot(state: .paused,  lat: 3, lon: 3))
        XCTAssertEqual(store.breadcrumb.count, 3)

        // Stale position in idle must not accumulate.
        store.apply(snapshot: snapshot(state: .idle,        lat: 99, lon: 99))
        store.apply(snapshot: snapshot(state: .stopping,    lat: 99, lon: 99))
        store.apply(snapshot: snapshot(state: .error,       lat: 99, lon: 99))
        store.apply(snapshot: snapshot(state: .reconnecting,lat: 99, lon: 99))
        XCTAssertEqual(store.breadcrumb.count, 3)

        // currentPosition still updates regardless of state so the marker tracks.
        XCTAssertEqual(store.currentPosition?.latitude, 99)
    }

    func testStartingState_includedInBreadcrumb() {
        let store = SessionStore()
        store.apply(snapshot: snapshot(state: .starting, lat: 1, lon: 1))
        XCTAssertEqual(store.breadcrumb.count, 1)
    }

    func testClearBreadcrumbResetsTrail() {
        let store = SessionStore()
        store.apply(snapshot: snapshot(state: .running, lat: 1, lon: 1))
        store.clearBreadcrumb()
        XCTAssertEqual(store.breadcrumb.count, 0)
    }

    func testPinSelectionRequiresOriginThenDestination() {
        let store = SessionStore()
        XCTAssertEqual(store.pinSelectionStage, .origin)
        store.setPin(at: CLLocationCoordinate2D(latitude: 1, longitude: 1))
        XCTAssertNotNil(store.origin)
        XCTAssertEqual(store.pinSelectionStage, .destination)
        store.setPin(at: CLLocationCoordinate2D(latitude: 2, longitude: 2))
        XCTAssertNotNil(store.destination)
        XCTAssertEqual(store.destinations.count, 1)
        XCTAssertEqual(store.pinSelectionStage, .ready)
    }

    func testSetPinAppendsAdditionalDestinations() {
        let store = SessionStore()
        store.setPin(at: CLLocationCoordinate2D(latitude: 1, longitude: 1)) // origin
        store.setPin(at: CLLocationCoordinate2D(latitude: 2, longitude: 2)) // dest 1
        store.setPin(at: CLLocationCoordinate2D(latitude: 3, longitude: 3)) // dest 2
        XCTAssertEqual(store.destinations.count, 2)
        XCTAssertEqual(store.destinations.last?.latitude, 3)
        XCTAssertEqual(store.pinSelectionStage, .ready)
    }

    func testRemoveDestination() {
        let store = SessionStore()
        store.setPin(at: CLLocationCoordinate2D(latitude: 1, longitude: 1))
        store.setPin(at: CLLocationCoordinate2D(latitude: 2, longitude: 2))
        store.setPin(at: CLLocationCoordinate2D(latitude: 3, longitude: 3))
        store.removeDestination(at: 0)
        XCTAssertEqual(store.destinations.count, 1)
        XCTAssertEqual(store.destinations.first?.latitude, 3)
    }

    func testNilCoordinatesAreNoOp() {
        let store = SessionStore()
        store.apply(snapshot: snapshot(state: .idle, lat: nil, lon: nil))
        XCTAssertNil(store.currentPosition)
        XCTAssertEqual(store.breadcrumb.count, 0)
        // latest is still recorded so the UI can render state-only updates.
        XCTAssertEqual(store.latest?.state, .idle)
    }

    func testNilCoordinatesClearCurrentPosition() {
        let store = SessionStore()
        store.apply(snapshot: snapshot(state: .running, lat: 5, lon: 5))
        XCTAssertNotNil(store.currentPosition)

        // A reset broadcast carries nil coords — the marker must clear.
        store.apply(snapshot: snapshot(state: .idle, lat: nil, lon: nil))
        XCTAssertNil(store.currentPosition)
    }

    func testResetPinsClearsBoth() {
        let store = SessionStore()
        store.setPin(at: CLLocationCoordinate2D(latitude: 1, longitude: 1))
        store.setPin(at: CLLocationCoordinate2D(latitude: 2, longitude: 2))
        store.resetPins()
        XCTAssertNil(store.origin)
        XCTAssertNil(store.destination)
        XCTAssertEqual(store.destinations.count, 0)
        XCTAssertEqual(store.pinSelectionStage, .origin)
    }
}
