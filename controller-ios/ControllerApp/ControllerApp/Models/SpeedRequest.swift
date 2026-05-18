import Foundation

struct SpeedRequest: Codable, Equatable {
    let speedKmh: Double

    enum CodingKeys: String, CodingKey {
        case speedKmh = "speed_kmh"
    }
}
