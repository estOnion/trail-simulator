import Foundation

struct SpeedRequest: Codable, Equatable, Sendable {
    let speedKmh: Double

    enum CodingKeys: String, CodingKey {
        case speedKmh = "speed_kmh"
    }
}
