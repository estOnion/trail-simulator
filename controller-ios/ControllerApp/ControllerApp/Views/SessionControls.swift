import SwiftUI
import CoreLocation

struct SessionControls: View {
    @ObservedObject var actions: SessionActions
    @EnvironmentObject var store: SessionStore

    private var client: BackendClient { actions.client }
    private var inFlight: Bool { actions.inFlight }

    var body: some View {
        VStack(spacing: 12) {
            if !store.destinations.isEmpty {
                DestinationsList()
            }

            HStack {
                Text("Speed").font(.subheadline)
                Slider(value: $store.speedKmh, in: 0.5...20.0, step: 0.5)
                Text(String(format: "%.1f km/h", store.speedKmh)).font(.subheadline).monospacedDigit()
            }

            HStack(spacing: 8) {
                primaryButton
                if store.state.showsPause {
                    Button("Pause") { Task { await actions.perform { try await client.pause() } } }
                        .buttonStyle(.bordered)
                }
                if store.state.showsResume {
                    Button("Resume") { Task { await actions.perform { try await client.resume() } } }
                        .buttonStyle(.bordered)
                }
                if store.state.showsStop {
                    Button("Stop", role: .destructive) {
                        Task { await actions.perform { try await client.stop() } }
                    }
                    .buttonStyle(.bordered)
                }
                if store.state.showsResetGPS(hasPosition: store.currentPosition != nil) {
                    Button("Reset GPS", role: .destructive) {
                        Task {
                            await actions.perform { try await client.reset() }
                            store.clearBreadcrumb()
                        }
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let err = actions.errorMessage {
                Text(err).font(.caption).foregroundStyle(.red)
            }
        }
        .alert("Cooldown active", isPresented: Binding(get: { actions.cooldown != nil }, set: { if !$0 { actions.cooldown = nil } })) {
            Button("OK", role: .cancel) { actions.cooldown = nil }
            Button("Skip cooldown") {
                Task { await actions.startWalk(store: store, skipCooldown: true) }
                actions.cooldown = nil
            }
        } message: {
            if let c = actions.cooldown {
                Text("Reason: \(c.reason)\nJump: \(String(format: "%.1f", c.jumpKm)) km\nWait: \(Int(c.requiredWaitS)) s")
            }
        }
    }

    @ViewBuilder
    private var primaryButton: some View {
        let canStart = store.state.canStartWalk(pinStage: store.pinSelectionStage, inFlight: inFlight)
        Button {
            Task { await actions.startWalk(store: store, skipCooldown: false) }
        } label: {
            Label(inFlight ? "Working…" : "Walk", systemImage: "figure.walk")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(!canStart)
    }
}

private struct DestinationsList: View {
    @EnvironmentObject var store: SessionStore

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Destinations").font(.caption).foregroundStyle(.secondary)
            ForEach(Array(store.destinations.enumerated()), id: \.offset) { idx, d in
                HStack {
                    Image(systemName: idx == store.destinations.count - 1 ? "flag.fill" : "mappin.circle.fill")
                        .foregroundStyle(idx == store.destinations.count - 1 ? .red : .orange)
                    Text("\(idx + 1). \(String(format: "%.4f, %.4f", d.latitude, d.longitude))")
                        .font(.caption)
                        .monospacedDigit()
                    Spacer()
                    Button(role: .destructive) {
                        store.removeDestination(at: idx)
                    } label: {
                        Image(systemName: "minus.circle.fill")
                            .foregroundStyle(.red)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Remove destination \(idx + 1)")
                }
            }
            Text("Tap the map or search to add more stops.")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
