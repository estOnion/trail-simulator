import Foundation

enum SessionState: String, Codable, Equatable, Sendable {
    case idle, starting, running, paused, stopping, reconnecting, error
    case following
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = SessionState(rawValue: raw) ?? .unknown
    }
}
