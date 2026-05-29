import SwiftUI

struct RootView: View {
    @StateObject private var store = SessionStore()
    @EnvironmentObject var health: HealthStore
    @State private var config: BackendConfig = BackendConfig.loadFromUserDefaults()
    @State private var client: BackendClient
    @State private var subscriber = LiveStatusSubscriber()

    init() {
        let cfg = BackendConfig.loadFromUserDefaults()
        _config = State(initialValue: cfg)
        _client = State(initialValue: BackendClient(baseURL: cfg.baseURL, deviceName: cfg.deviceName))
    }

    private struct ConnectionKey: Equatable {
        let url: URL
        let deviceName: String?
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
        .task(id: ConnectionKey(url: config.baseURL, deviceName: config.deviceName, connected: store.isConnected)) {
            await subscriber.cancel()
            health.disconnect()
            await client.updateBaseURL(config.baseURL)
            await client.updateDeviceName(config.deviceName)
            guard store.isConnected else { return }
            let label = config.deviceName ?? "iPhone"
            health.connect(baseURL: config.baseURL, label: label)
            let stream = await subscriber.start(baseURL: config.baseURL, deviceName: config.deviceName)
            for await snap in stream {
                store.apply(snapshot: snap)
            }
        }
    }
}
