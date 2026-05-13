import Foundation
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
        let start = end.addingTimeInterval(-Double(count))  // 1 s per step as a reasonable sample span
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
            await MainActor.run { lastError = "write failed: \(error.localizedDescription)" }
        }
    }

    // Debug helper — writes 100 steps over the last 60 s.
    func writeDebugSample() async {
        let end = Date()
        let start = end.addingTimeInterval(-60)
        let stepType = HKQuantityType(.stepCount)
        let sample = HKQuantitySample(
            type: stepType,
            quantity: HKQuantity(unit: .count(), doubleValue: 100),
            start: start,
            end: end
        )
        do {
            try await store.save(sample)
        } catch {
            await MainActor.run { lastError = "debug write failed: \(error.localizedDescription)" }
        }
    }
}
