import Foundation
import Combine
import CoreLocation

/// Thin wrapper over CLLocationManager that just requests "When In Use"
/// authorization and reports the most recent location to a callback.
/// MapScreen uses this to drive its "center on me" button.
@MainActor
final class LocationAuth: NSObject, ObservableObject {
    private let manager = CLLocationManager()
    @Published private(set) var lastLocation: CLLocationCoordinate2D? = nil
    @Published private(set) var authorized: Bool = false

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        refreshAuth()
    }

    func requestAuthorizationAndFix() {
        switch manager.authorizationStatus {
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        case .authorizedAlways, .authorizedWhenInUse:
            authorized = true
            manager.requestLocation()
        default:
            authorized = false
        }
    }

    private func refreshAuth() {
        let s = manager.authorizationStatus
        authorized = (s == .authorizedAlways || s == .authorizedWhenInUse)
    }
}

extension LocationAuth: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
        Task { @MainActor in
            self.refreshAuth()
            if self.authorized { m.requestLocation() }
        }
    }
    nonisolated func locationManager(_ m: CLLocationManager, didUpdateLocations locs: [CLLocation]) {
        guard let c = locs.last?.coordinate else { return }
        Task { @MainActor in self.lastLocation = c }
    }
    nonisolated func locationManager(_ m: CLLocationManager, didFailWithError error: Error) { /* ignored */ }
}
