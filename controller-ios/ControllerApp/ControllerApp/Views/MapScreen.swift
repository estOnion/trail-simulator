import SwiftUI
import MapKit
import CoreLocation

struct MapScreen: View {
    @EnvironmentObject var store: SessionStore
    @State private var camera: MapCameraPosition = .region(
        MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: 35.68, longitude: 139.69),
            span: MKCoordinateSpan(latitudeDelta: 0.05, longitudeDelta: 0.05)
        )
    )

    var body: some View {
        ZStack {
            MapReader { proxy in
                Map(position: $camera) {
                    if let o = store.origin {
                        Marker("Start", coordinate: o).tint(.green)
                    }
                    if let d = store.destination {
                        Marker("End", coordinate: d).tint(.red)
                    }
                    if let p = store.currentPosition {
                        Annotation("", coordinate: p) {
                            Circle()
                                .fill(.blue)
                                .frame(width: 14, height: 14)
                                .overlay(Circle().stroke(.white, lineWidth: 2))
                        }
                    }
                    if !store.breadcrumb.isEmpty {
                        MapPolyline(coordinates: store.breadcrumb)
                            .stroke(.green, lineWidth: 4)
                    }
                }
                .onTapGesture { screenPoint in
                    guard let coord = proxy.convert(screenPoint, from: .local) else { return }
                    store.setPin(at: coord)
                }
            }

            // Crosshair overlay when not yet ready, to confirm tap target.
            if store.pinSelectionStage != .ready {
                Image(systemName: "plus.viewfinder")
                    .font(.system(size: 28, weight: .light))
                    .foregroundStyle(.secondary)
                    .allowsHitTesting(false)
            }

            VStack {
                HStack {
                    Spacer()
                    Button {
                        store.resetPins()
                        store.clearBreadcrumb()
                    } label: {
                        Label("Reset pins", systemImage: "xmark.circle.fill")
                            .labelStyle(.iconOnly)
                            .font(.title2)
                            .padding(10)
                            .background(.thinMaterial, in: Circle())
                    }
                    .padding(.top, 12)
                    .padding(.trailing, 12)
                    .accessibilityLabel("Reset pins")
                }
                Spacer()
            }
        }
    }
}
