import Foundation

struct StepEvent: Decodable {
    let type: String
    let steps: Int?
    let distance_m: Double?
    let ts: String?
}

#if DEBUG
extension StepEvent {
    static func makeForTest(type: String, steps: Int? = nil, distance_m: Double? = nil, ts: String? = nil) -> StepEvent {
        let stepsLit: String = steps.map { "\($0)" } ?? "null"
        let distLit: String = distance_m.map { "\($0)" } ?? "null"
        let tsLit: String = ts.map { "\"\($0)\"" } ?? "null"
        let json = "{\"type\":\"\(type)\",\"steps\":\(stepsLit),\"distance_m\":\(distLit),\"ts\":\(tsLit)}"
        return try! JSONDecoder().decode(StepEvent.self, from: Data(json.utf8))
    }
}
#endif
