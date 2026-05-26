import SwiftUI

@main
struct ControllerAppApp: App {
    @StateObject private var health = HealthStore()
    private let audioKeeper = BackgroundAudioKeeper()

    init() {
        audioKeeper.start()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(health)
                .task { await health.writer.requestAuthorization() }
        }
    }
}
