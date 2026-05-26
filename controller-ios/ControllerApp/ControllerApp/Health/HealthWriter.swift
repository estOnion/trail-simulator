import Foundation
import Combine
import HealthKit

@MainActor
final class HealthWriter: ObservableObject {
    private let store = HKHealthStore()
    @Published var authorized = false
    @Published var lastError: String?

    private var writeTypes: Set<HKSampleType> {
        [
            HKQuantityType(.stepCount),
            HKQuantityType(.distanceWalkingRunning),
        ]
    }

    func requestAuthorization() async {
        guard HKHealthStore.isHealthDataAvailable() else {
            lastError = "HealthKit not available on this device"
            return
        }
        do {
            try await store.requestAuthorization(toShare: writeTypes, read: [])
            authorized = true
        } catch {
            lastError = "HealthKit auth failed: \(error.localizedDescription)"
        }
    }

    func writeSteps(count: Int, distanceMeters: Double, end: Date) async {
        let start = end.addingTimeInterval(-Double(count))
        let stepType = HKQuantityType(.stepCount)
        let stepSample = HKQuantitySample(
            type: stepType,
            quantity: HKQuantity(unit: .count(), doubleValue: Double(count)),
            start: start,
            end: end
        )
        let distType = HKQuantityType(.distanceWalkingRunning)
        let distSample = HKQuantitySample(
            type: distType,
            quantity: HKQuantity(unit: .meter(), doubleValue: distanceMeters),
            start: start,
            end: end
        )
        do {
            try await store.save([stepSample, distSample])
        } catch {
            lastError = "write failed: \(error.localizedDescription)"
        }
    }
}
