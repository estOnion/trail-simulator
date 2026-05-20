import SwiftUI

struct RootView: View {
    @StateObject private var store = SessionStore()
    @State private var config: BackendConfig = BackendConfig.loadFromUserDefaults()
    @State private var client: BackendClient
    @State private var subscriber = LiveStatusSubscriber()
    @State private var showSettings = false

    init() {
        let cfg = BackendConfig.loadFromUserDefaults()
        _config = State(initialValue: cfg)
        _client = State(initialValue: BackendClient(baseURL: cfg.baseURL))
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SearchBar(client: client) { coord in
                    store.setPin(at: coord)
                }
                .padding(.horizontal)
                .padding(.top, 8)

                MapScreen()
                    .environmentObject(store)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                VStack(spacing: 10) {
                    SessionControls(client: client).environmentObject(store)
                    StepCompanionsPanel().environmentObject(store)
                }
                .padding(.horizontal)
                .padding(.vertical, 10)
            }
            .navigationTitle("Trail Controller")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    StatePill(state: store.state)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsScreen(config: $config, client: client)
            }
            .task {
                let stream = await subscriber.start(baseURL: config.baseURL)
                for await snap in stream {
                    store.apply(snapshot: snap)
                }
            }
            .onChange(of: config) { _, newConfig in
                Task {
                    await subscriber.cancel()
                    let stream = await subscriber.start(baseURL: newConfig.baseURL)
                    for await snap in stream {
                        store.apply(snapshot: snap)
                    }
                }
            }
        }
    }
}

private struct StatePill: View {
    let state: SessionState
    var body: some View {
        Text(state.rawValue)
            .font(.caption).bold()
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(color.opacity(0.2), in: Capsule())
            .foregroundStyle(color)
    }
    private var color: Color {
        switch state {
        case .running:      return .green
        case .paused:       return .orange
        case .stopping, .reconnecting: return .yellow
        case .error:        return .red
        case .starting:     return .blue
        case .idle:         return .secondary
        case .unknown:      return .secondary
        }
    }
}
