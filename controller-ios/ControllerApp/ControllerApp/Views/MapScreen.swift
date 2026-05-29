import SwiftUI
import MapKit
import CoreLocation

struct MapScreen: View {
    @EnvironmentObject var store: SessionStore
    @StateObject private var locator = LocationAuth()
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
                    UserAnnotation()
                    if let o = store.origin {
                        Marker("Start", coordinate: o).tint(.green)
                    }
                    ForEach(Array(store.destinations.enumerated()), id: \.offset) { idx, d in
                        let isLast = idx == store.destinations.count - 1
                        Marker(isLast ? "End" : "Stop \(idx + 1)", coordinate: d)
                            .tint(isLast ? .red : .orange)
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

            // Crosshair overlay until origin is set, to confirm tap target.
            if store.origin == nil {
                Image(systemName: "plus.viewfinder")
                    .font(.system(size: 28, weight: .light))
                    .foregroundStyle(.secondary)
                    .allowsHitTesting(false)
            }

            VStack {
                HStack {
                    Spacer()
                    VStack(spacing: 8) {
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
                        .accessibilityLabel("Reset pins")

                        Button {
                            locator.requestAuthorizationAndFix()
                        } label: {
                            Label("My location", systemImage: "location.fill")
                                .labelStyle(.iconOnly)
                                .font(.title2)
                                .padding(10)
                                .background(.thinMaterial, in: Circle())
                        }
                        .accessibilityLabel("Center on my location")
                    }
                    .padding(.top, 12)
                    .padding(.trailing, 12)
                }
                Spacer()
            }
        }
        .onChange(of: store.cameraFocus) { _, focus in
            guard let focus else { return }
            withAnimation {
                camera = .region(MKCoordinateRegion(
                    center: focus.coordinate,
                    span: MKCoordinateSpan(latitudeDelta: 0.02, longitudeDelta: 0.02)
                ))
            }
        }
        .onChange(of: locator.lastLocation?.latitude) { _, _ in
            guard let loc = locator.lastLocation else { return }
            withAnimation {
                camera = .region(MKCoordinateRegion(
                    center: loc,
                    span: MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)
                ))
            }
        }
    }
}
