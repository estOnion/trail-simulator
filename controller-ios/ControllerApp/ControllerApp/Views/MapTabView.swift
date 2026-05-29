import SwiftUI

struct MapTabView: View {
    @EnvironmentObject var store: SessionStore
    let client: BackendClient

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                SearchBar(client: client) { coord in
                    store.setPin(at: coord)
                    store.focusCamera(on: coord)
                }
                .padding(.horizontal)
                .padding(.top, 8)

                MapScreen()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)

                VStack(spacing: 10) {
                    SessionControls(client: client)
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
            }
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
