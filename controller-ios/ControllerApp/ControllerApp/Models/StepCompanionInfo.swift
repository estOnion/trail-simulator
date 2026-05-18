import Foundation

struct StepCompanionInfo: Codable, Equatable, Identifiable {
    let label: String
    let udid: String?
    let connectedAtIso: String
    let lastHeartbeatIso: String
    let totalAcked: Int

    var id: String { udid ?? label }
}
