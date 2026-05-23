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
        guard let o = store.origin, let d = store.destination else { return }
        store.clearBreadcrumb()
        await action {
            let req = SessionStartRequest(
                startLat: o.latitude, startLon: o.longitude,
                destinations: [Destination(lat: d.latitude, lon: d.longitude)],
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
