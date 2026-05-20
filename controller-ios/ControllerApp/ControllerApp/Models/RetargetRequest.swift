import Foundation

struct RetargetRequest: Codable, Equatable, Sendable {
    let destinations: [Destination]
    let loop: Bool?
}
