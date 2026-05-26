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

    var body: some View {
        TabView {
            MapTabView(client: client)
                .environmentObject(store)
                .tabItem { Label("Map", systemImage: "map") }

            HealthTabView(health: health)
                .tabItem { Label("Health", systemImage: "heart.text.square") }

            SettingsTabView(config: $config, client: client)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .task {
            let stream = await subscriber.start(baseURL: config.baseURL)
            health.connect(baseURL: config.baseURL, label: UIDevice.current.name)
            for await snap in stream {
                store.apply(snapshot: snap)
            }
        }
        .onChange(of: config) { _, newConfig in
            Task {
                await subscriber.cancel()
                health.reconnect(baseURL: newConfig.baseURL, label: UIDevice.current.name)
                let stream = await subscriber.start(baseURL: newConfig.baseURL)
                for await snap in stream {
                    store.apply(snapshot: snap)
                }
            }
        }
    }
}
