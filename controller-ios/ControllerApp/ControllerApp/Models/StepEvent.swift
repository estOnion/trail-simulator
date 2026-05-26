import Foundation

struct StepEvent: Decodable {
    let type: String
    let steps: Int?
    let distance_m: Double?
    let ts: String?
}
