import Foundation

enum BackendError: Error, Equatable, Sendable {
    case transport(String)             // URLSession failures, decode failures
    case sessionAlreadyActive(String)  // 409 from /api/session
    case sessionNotActive(String)      // 409 from /api/retarget
    case cooldown(CooldownDetail)      // 429 from /api/session
    case routing(String)               // 502 from /api/retarget or /api/speed
    case server(Int, String)           // any other non-2xx with detail
}
