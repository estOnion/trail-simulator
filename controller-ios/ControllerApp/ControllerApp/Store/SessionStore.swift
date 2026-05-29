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
    @Published var destinations: [CLLocationCoordinate2D] = []
    @Published var speedKmh: Double = 4.0   // default walking pace
    @Published var lastError: BackendError? = nil

    // Bumped whenever the user picks a search result or taps "current location"
    // so MapScreen can recenter without us owning the camera.
    @Published var cameraFocus: CameraFocus? = nil

    // User-controlled connection toggle. Drives the WS lifecycle in RootView.
    @Published var isConnected: Bool = true

    // When set, the Map view watches a leader's live stream instead of this
    // device's own session (view-only follow). RootView repoints the subscriber.
    @Published var watchingLeaderId: String? = nil

    struct CameraFocus: Equatable {
        let coordinate: CLLocationCoordinate2D
        let id: UUID

        static func == (lhs: CameraFocus, rhs: CameraFocus) -> Bool { lhs.id == rhs.id }
    }

    var destination: CLLocationCoordinate2D? { destinations.last }

    var pinSelectionStage: PinStage {
        if origin == nil { return .origin }
        if destinations.isEmpty { return .destination }
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
        if origin == nil {
            origin = coord
        } else {
            destinations.append(coord)
        }
    }

    func removeDestination(at index: Int) {
        guard destinations.indices.contains(index) else { return }
        destinations.remove(at: index)
    }

    func resetPins() {
        origin = nil
        destinations.removeAll()
    }

    func focusCamera(on coord: CLLocationCoordinate2D) {
        cameraFocus = CameraFocus(coordinate: coord, id: UUID())
    }
}
