import SwiftUI
import UIKit

struct RootView: View {
    @StateObject private var store = SessionStore()
    @EnvironmentObject var health: HealthStore
    @State private var config: BackendConfig = BackendConfig.loadFromUserDefaults()
    @State private var client: BackendClient
    @State private var subscriber = LiveStatusSubscriber()

    init() {
        let cfg = BackendConfig.loadFromUserDefaults()
        _config = State(initialValue: cfg)
        _client = State(initialValue: BackendClient(baseURL: cfg.baseURL))
    }

    private struct ConnectionKey: Equatable {
        let url: URL
        let connected: Bool
    }

    var body: some View {
        TabView {
            MapTabView(client: client)
                .environmentObject(store)
                .tabItem { Label("Map", systemImage: "map") }

            HealthTabView(health: health)
                .tabItem { Label("Health", systemImage: "heart.text.square") }

            SettingsTabView(config: $config, client: client)
                .environmentObject(store)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .task(id: ConnectionKey(url: config.baseURL, connected: store.isConnected)) {
            await subscriber.cancel()
            health.disconnect()
            guard store.isConnected else { return }
            health.connect(baseURL: config.baseURL, label: UIDevice.current.name)
            let stream = await subscriber.start(baseURL: config.baseURL, deviceName: UIDevice.current.name)
            for await snap in stream {
                store.apply(snapshot: snap)
            }
        }
    }
}
