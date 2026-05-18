import Foundation

struct CooldownDetail: Codable, Equatable {
    let cooldown: Bool
    let requiredWaitS: Double
    let jumpKm: Double
    let reason: String

    enum CodingKeys: String, CodingKey {
        case cooldown
        case requiredWaitS = "required_wait_s"
        case jumpKm = "jump_km"
        case reason
    }
}
