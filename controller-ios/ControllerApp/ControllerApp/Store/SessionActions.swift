import Foundation
import Combine
import CoreLocation

/// The session requests the Map tab sends (start, pause, resume, stop, reset)
/// and the state around them: the in-flight flag, the cooldown prompt and the
/// failure text. One instance is shared by the controls row and the state
/// pill's "Try again" (IOS-14), so both go through the same start request,
/// gating and error handling.
@MainActor
final class SessionActions: ObservableObject {
    let client: BackendClient

    @Published private(set) var inFlight: Bool = false
    @Published var cooldown: CooldownDetail? = nil
    @Published var errorMessage: String? = nil

    init(client: BackendClient) {
        self.client = client
    }

    /// Sends the same start that the Walk button sends. A no-op without an
    /// origin and a destination.
    func startWalk(store: SessionStore, skipCooldown: Bool) async {
        guard let o = store.origin, !store.destinations.isEmpty else { return }
        let dests = store.destinations.map { Destination(lat: $0.latitude, lon: $0.longitude) }
        let speed = store.speedKmh
        store.clearBreadcrumb()
        await perform {
            let req = SessionStartRequest(
                startLat: o.latitude, startLon: o.longitude,
                destinations: dests,
                speedKmh: speed,
                loop: false,
                skipCooldown: skipCooldown
            )
            _ = try await self.client.startSession(req)
        }
    }

    func perform(_ block: @escaping () async throws -> Void) async {
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
