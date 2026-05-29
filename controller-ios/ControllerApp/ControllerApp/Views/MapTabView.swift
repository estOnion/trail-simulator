import SwiftUI

struct MapTabView: View {
    @EnvironmentObject var store: SessionStore
    let client: BackendClient
    @State private var showFollow = false

    private var isFollowing: Bool {
        store.watchingLeaderId != nil || store.state == .following
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SearchBar(client: client) { coord in
                    store.setPin(at: coord)
                    store.focusCamera(on: coord)
                }
                .padding(.horizontal)
                .padding(.top, 8)

                if isFollowing {
                    HStack {
                        Image(systemName: "dot.radiowaves.left.and.right")
                        Text(store.watchingLeaderId != nil ? "Watching a leader" : "Mirroring a leader")
                            .font(.caption)
                        Spacer()
                        Button("Stop") { Task { await stopFollowing() } }
                            .font(.caption).tint(.red)
                    }
                    .padding(.horizontal).padding(.vertical, 6)
                    .background(.thinMaterial)
                }

                MapScreen()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                VStack(spacing: 10) {
                    SessionControls(client: client)
                        .disabled(isFollowing)
                    StepCompanionsPanel()
                }
                .padding(.horizontal)
                .padding(.vertical, 10)
            }
            .navigationTitle("Trail Controller")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    MapStatePill(state: store.state)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showFollow = true } label: {
                        Label("Follow", systemImage: "person.2.wave.2")
                    }
                }
            }
            .sheet(isPresented: $showFollow) {
                FollowSheet(client: client).environmentObject(store)
            }
        }
    }

    private func stopFollowing() async {
        if store.watchingLeaderId != nil {
            store.watchingLeaderId = nil
        } else {
            try? await client.unfollow()
        }
    }
}

private struct MapStatePill: View {
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
        case .following:    return .teal
        case .idle:         return .secondary
        case .unknown:      return .secondary
        }
    }
}
