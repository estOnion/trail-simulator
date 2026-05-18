import Foundation

struct StatusSnapshot: Codable, Equatable {
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
}
