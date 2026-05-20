import SwiftUI
import CoreLocation

struct SearchBar: View {
    let client: BackendClient
    let onPick: (CLLocationCoordinate2D) -> Void

    @State private var query: String = ""
    @State private var results: [SearchResult] = []
    @State private var loading: Bool = false
    @State private var errorMessage: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search address or place", text: $query)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.search)
                    .onSubmit { Task { await runSearch() } }
                if loading {
                    ProgressView().scaleEffect(0.7)
                } else if !query.isEmpty {
                    Button { query = ""; results = [] } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }
                }
            }
            .padding(10)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))

            if let err = errorMessage {
                Text(err).font(.caption).foregroundStyle(.red).padding(.horizontal, 4)
            }

            if !results.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(results) { r in
                        Button {
                            onPick(CLLocationCoordinate2D(latitude: r.lat, longitude: r.lon))
                            query = r.displayName
                            results = []
                        } label: {
                            VStack(alignment: .leading) {
                                Text(r.displayName).font(.subheadline).lineLimit(2)
                                Text(r.type).font(.caption).foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 6)
                            .padding(.horizontal, 8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                        Divider()
                    }
                }
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
            }
        }
    }

    private func runSearch() async {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { results = []; return }
        loading = true; errorMessage = nil; defer { loading = false }
        do {
            results = try await client.search(query: q)
            if results.isEmpty { errorMessage = "No results" }
        } catch {
            errorMessage = "Search failed"
            results = []
        }
    }
}
