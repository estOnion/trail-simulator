import SwiftUI
import CoreLocation

struct SessionControls: View {
    let client: BackendClient
    @EnvironmentObject var store: SessionStore
    @State private var inFlight: Bool = false
    @State private var cooldown: CooldownDetail? = nil
    @State private var errorMessage: String? = nil

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
                if store.state == .running {
                    Button("Pause") { Task { await action { try await client.pause() } } }
                        .buttonStyle(.bordered)
                }
                if store.state == .paused {
                    Button("Resume") { Task { await action { try await client.resume() } } }
                        .buttonStyle(.bordered)
                }
                if [.starting, .running, .paused, .reconnecting].contains(store.state) {
                    Button("Stop", role: .destructive) {
                        Task { await action { try await client.stop() } }
                    }
                    .buttonStyle(.bordered)
                }
                if store.state == .idle, store.currentPosition != nil {
                    Button("Reset GPS", role: .destructive) {
                        Task {
                            await action { try await client.reset() }
                            store.clearBreadcrumb()
                        }
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let err = errorMessage {
                Text(err).font(.caption).foregroundStyle(.red)
            }
        }
        .alert("Cooldown active", isPresented: Binding(get: { cooldown != nil }, set: { if !$0 { cooldown = nil } })) {
            Button("OK", role: .cancel) { cooldown = nil }
            Button("Skip cooldown") {
                Task { await startSession(skipCooldown: true) }
                cooldown = nil
            }
        } message: {
            if let c = cooldown {
                Text("Reason: \(c.reason)\nJump: \(String(format: "%.1f", c.jumpKm)) km\nWait: \(Int(c.requiredWaitS)) s")
            }
        }
    }

    @ViewBuilder
    private var primaryButton: some View {
        let canStart = store.pinSelectionStage == .ready && store.state == .idle
        Button {
            Task { await startSession(skipCooldown: false) }
        } label: {
            Label(inFlight ? "Working…" : "Walk", systemImage: "figure.walk")
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .disabled(!canStart || inFlight)
    }

    private func startSession(skipCooldown: Bool) async {
        guard let o = store.origin, !store.destinations.isEmpty else { return }
        let dests = store.destinations.map { Destination(lat: $0.latitude, lon: $0.longitude) }
        store.clearBreadcrumb()
        await action {
            let req = SessionStartRequest(
                startLat: o.latitude, startLon: o.longitude,
                destinations: dests,
                speedKmh: store.speedKmh,
                loop: false,
                skipCooldown: skipCooldown
            )
            _ = try await client.startSession(req)
        }
    }

    private func action(_ block: @escaping () async throws -> Void) async {
        inFlight = true; errorMessage = nil; defer { inFlight = false }
        do {
            try await block()
        } catch BackendError.cooldown(let d) {
            cooldown = d
        } catch BackendError.sessionAlreadyActive(let m) {
            errorMessage = "Session already active: \(m)"
        } catch BackendError.routing(let m) {
            errorMessage = "Routing error: \(m)"
        } catch BackendError.server(let code, let m) {
            errorMessage = "Server \(code): \(m)"
        } catch BackendError.transport(let m) {
            errorMessage = "Network: \(m)"
        } catch {
            errorMessage = "\(error)"
        }
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
