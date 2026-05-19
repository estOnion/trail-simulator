import Foundation

struct StepCompanionInfo: Codable, Equatable, Identifiable, Sendable {
    let label: String
    let udid: String?
    let connectedAtIso: String
    let lastHeartbeatIso: String
    let totalAcked: Int

    var id: String { udid ?? label }

    enum CodingKeys: String, CodingKey {
        case label
        case udid
        case connectedAtIso = "connected_at_iso"
        case lastHeartbeatIso = "last_heartbeat_iso"
        case totalAcked = "total_acked"
    }
}
