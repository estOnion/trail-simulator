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

// Which session controls the Controller app offers in each state (IOS-09, IOS-10).
// Kept as pure rules so they can be unit tested; `SessionControls` only calls them.
extension SessionState {
    /// "Walk" is available from idle and from error (the backend accepts a new
    /// start from either, SES-04) once an origin and a destination are placed.
    func canStartWalk(pinStage: SessionStore.PinStage, inFlight: Bool) -> Bool {
        pinStage == .ready && (self == .idle || self == .error) && !inFlight
    }

    var showsPause: Bool { self == .running }

    var showsResume: Bool { self == .paused }

    /// Also offered in error: on the backend it cancels a pending auto-resume (SES-16).
    var showsStop: Bool {
        [.starting, .running, .paused, .reconnecting, .error].contains(self)
    }

    /// In error the reset is offered even without a position, so a stale error
    /// can be cleared without walking (SES-21).
    func showsResetGPS(hasPosition: Bool) -> Bool {
        switch self {
        case .idle: return hasPosition
        case .error: return true
        default: return false
        }
    }
}
