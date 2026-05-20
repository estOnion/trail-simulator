import Foundation

struct SessionStartRequest: Codable, Equatable, Sendable {
    let startLat: Double
    let startLon: Double
    let destinations: [Destination]
    let speedKmh: Double
    let loop: Bool
    let skipCooldown: Bool

    enum CodingKeys: String, CodingKey {
        case startLat = "start_lat"
        case startLon = "start_lon"
        case destinations
        case speedKmh = "speed_kmh"
        case loop
        case skipCooldown = "skip_cooldown"
    }
}
