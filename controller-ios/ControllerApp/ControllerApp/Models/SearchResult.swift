import Foundation

struct SearchResult: Codable, Equatable, Identifiable, Sendable {
    let displayName: String
    let lat: Double
    let lon: Double
    let type: String

    var id: String { "\(lat),\(lon),\(displayName)" }

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case lat
        case lon
        case type
    }
}

struct SearchResponse: Codable, Equatable, Sendable {
    let results: [SearchResult]
}
