import XCTest
@testable import ControllerApp

@MainActor
final class HealthStoreTests: XCTestCase {
    private var defaults: UserDefaults!

    override func setUp() async throws {
        defaults = UserDefaults(suiteName: "HealthStoreTests.\(UUID().uuidString)")!
    }

    func testDefaultsEnabledTrueAndZeroCounters() {
        let store = HealthStore(defaults: defaults)
        XCTAssertTrue(store.enabled)
        XCTAssertEqual(store.sessionSteps, 0)
        XCTAssertEqual(store.sessionDistanceM, 0)
        XCTAssertEqual(store.cumulativeSteps, 0)
        XCTAssertEqual(store.cumulativeDistanceM, 0)
    }

    func testApplyStepsEventIncrementsSessionAndCumulative() {
        let store = HealthStore(defaults: defaults)
        let event = StepEvent.makeForTest(type: "steps", steps: 10, distance_m: 7.5)
        store.apply(event: event)
        XCTAssertEqual(store.sessionSteps, 10)
        XCTAssertEqual(store.sessionDistanceM, 7.5, accuracy: 0.001)
        XCTAssertEqual(store.cumulativeSteps, 10)
        XCTAssertEqual(store.cumulativeDistanceM, 7.5, accuracy: 0.001)
    }

    func testNonStepsEventIgnored() {
        let store = HealthStore(defaults: defaults)
        store.apply(event: StepEvent.makeForTest(type: "hello"))
        XCTAssertEqual(store.sessionSteps, 0)
        XCTAssertEqual(store.cumulativeSteps, 0)
    }

    func testCumulativePersistsAcrossInits() {
        let s1 = HealthStore(defaults: defaults)
        s1.apply(event: StepEvent.makeForTest(type: "steps", steps: 5, distance_m: 4.0))
        let s2 = HealthStore(defaults: defaults)
        XCTAssertEqual(s2.cumulativeSteps, 5)
        XCTAssertEqual(s2.cumulativeDistanceM, 4.0, accuracy: 0.001)
        XCTAssertEqual(s2.sessionSteps, 0, "session counters do not persist")
    }

    func testTogglingEnabledResetsSession() {
        let store = HealthStore(defaults: defaults)
        store.apply(event: StepEvent.makeForTest(type: "steps", steps: 5, distance_m: 4.0))
        store.enabled = false
        store.enabled = true
        XCTAssertEqual(store.sessionSteps, 0)
        XCTAssertEqual(store.sessionDistanceM, 0)
    }
}
