import Foundation

struct SearchResult: Codable, Equatable, Identifiable {
    let displayName: String
    let lat: Double
    let lon: Double
    let type: String

    var id: String { "\(lat),\(lon),\(displayName)" }
}

struct SearchResponse: Codable, Equatable {
    let results: [SearchResult]
}
