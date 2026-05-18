import Foundation

struct RetargetRequest: Codable, Equatable {
    let destinations: [Destination]
    let loop: Bool?
}
