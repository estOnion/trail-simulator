import SwiftUI
import HealthKit

@main
struct StepCompanionApp: App {
    @StateObject private var writer = HealthWriter()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(writer)
                .task { await writer.requestAuthorization() }
        }
    }
}
