import Foundation
import CoreLocation
import Combine

@MainActor
final class SessionStore: ObservableObject {

    enum PinStage: Equatable { case origin, destination, ready }

    @Published private(set) var latest: StatusSnapshot? = nil
    @Published private(set) var breadcrumb: [CLLocationCoordinate2D] = []
    @Published private(set) var currentPosition: CLLocationCoordinate2D? = nil
    @Published var origin: CLLocationCoordinate2D? = nil
    @Published var destination: CLLocationCoordinate2D? = nil
    @Published var speedKmh: Double = 4.0   // default walking pace
    @Published var lastError: BackendError? = nil

    var pinSelectionStage: PinStage {
        if origin == nil { return .origin }
        if destination == nil { return .destination }
        return .ready
    }

    var state: SessionState { latest?.state ?? .idle }

    // Active states gate breadcrumb accumulation — replicates the May 13
    // web-UI fix where idle/stopping/error/reconnecting carried stale
    // coordinates from the previous route and would otherwise splice into
    // the new trail.
    static let activeStates: Set<SessionState> = [.starting, .running, .paused]

    func apply(snapshot: StatusSnapshot) {
        latest = snapshot

        if let lat = snapshot.currentLat, let lon = snapshot.currentLon {
            let coord = CLLocationCoordinate2D(latitude: lat, longitude: lon)
            currentPosition = coord
            if Self.activeStates.contains(snapshot.state) {
                breadcrumb.append(coord)
            }
        } else {
            currentPosition = nil
        }
    }

    func clearBreadcrumb() {
        breadcrumb.removeAll()
    }

    func setPin(at coord: CLLocationCoordinate2D) {
        switch pinSelectionStage {
        case .origin:       origin = coord
        case .destination:  destination = coord
        case .ready:        break
        }
    }

    func resetPins() {
        origin = nil
        destination = nil
    }
}
