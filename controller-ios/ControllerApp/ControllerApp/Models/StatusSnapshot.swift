import Foundation

struct StatusSnapshot: Codable, Equatable, Sendable {
    let state: SessionState
    let sessionId: Int?
    let currentLat: Double?
    let currentLon: Double?
    let targetLat: Double?
    let targetLon: Double?
    let speedKmh: Double
    let progressM: Double
    let totalM: Double
    let lastError: String?
    let cooldownRemainingS: Double
    let stepsSent: Int
    let stepCompanions: [StepCompanionInfo]
    let followingLeader: String? = nil

    enum CodingKeys: String, CodingKey {
        case state
        case sessionId = "session_id"
        case currentLat = "current_lat"
        case currentLon = "current_lon"
        case targetLat = "target_lat"
        case targetLon = "target_lon"
        case speedKmh = "speed_kmh"
        case progressM = "progress_m"
        case totalM = "total_m"
        case lastError = "last_error"
        case cooldownRemainingS = "cooldown_remaining_s"
        case stepsSent = "steps_sent"
        case stepCompanions = "step_companions"
        case followingLeader = "following_leader"
    }
}
