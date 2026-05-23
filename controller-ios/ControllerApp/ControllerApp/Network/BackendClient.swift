import Foundation

actor BackendClient {
    private var baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
        // All models declare explicit CodingKeys — no global key strategy
        // so models with snake_case keys (e.g. CooldownDetail) decode uniformly
        // across the happy path and the error path.
    }

    func updateBaseURL(_ url: URL) {
        baseURL = url
    }

    func fetchStatus() async throws -> StatusSnapshot {
        try await getJSON("/api/status", as: StatusSnapshot.self)
    }

    @discardableResult
    func startSession(_ req: SessionStartRequest) async throws -> String {
        try await postJSON("/api/session", body: req, decode: OkReason.self).reason
    }

    @discardableResult
    func retarget(_ req: RetargetRequest) async throws -> Bool {
        try await postJSON("/api/retarget", body: req, decode: Ok.self).ok
    }

    @discardableResult
    func setSpeed(_ kmh: Double) async throws -> Bool {
        try await postJSON("/api/speed", body: SpeedRequest(speedKmh: kmh), decode: Ok.self).ok
    }

    func pause() async throws { _ = try await postEmpty("/api/pause") }
    func resume() async throws { _ = try await postEmpty("/api/resume") }
    func stop() async throws { _ = try await postEmpty("/api/stop") }
    func reset() async throws { _ = try await postEmpty("/api/reset") }

    func search(query: String, limit: Int = 8) async throws -> [SearchResult] {
        var comps = URLComponents(url: baseURL.appendingPathComponent("api/search"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        let req = URLRequest(url: comps.url!)
        let (data, response) = try await session.data(for: req)
        try checkOk(response, data: data, isStart: false)
        return try decoder.decode(SearchResponse.self, from: data).results
    }

    // MARK: - private

    private struct Ok: Codable, Sendable { let ok: Bool }
    private struct OkReason: Codable, Sendable { let ok: Bool; let reason: String }

    private func getJSON<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
        let url = baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        let (data, resp) = try await session.data(for: URLRequest(url: url))
        try checkOk(resp, data: data, isStart: false)
        return try decoder.decode(T.self, from: data)
    }

    private func postJSON<Body: Encodable, T: Decodable>(_ path: String, body: Body, decode: T.Type) async throws -> T {
        var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(body)
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: path.hasSuffix("/session"))
        return try decoder.decode(T.self, from: data)
    }

    private func postEmpty(_ path: String) async throws -> Bool {
        var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        req.httpMethod = "POST"
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: false)
        return (try? decoder.decode(Ok.self, from: data).ok) ?? true
    }

    private func checkOk(_ response: URLResponse, data: Data, isStart: Bool) throws {
        guard let http = response as? HTTPURLResponse else {
            throw BackendError.transport("non-HTTP response")
        }
        if (200..<300).contains(http.statusCode) { return }

        // Try to decode the FastAPI {"detail": ...} envelope.
        let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]

        switch http.statusCode {
        case 409:
            let msg = (detail as? String) ?? "conflict"
            throw isStart ? BackendError.sessionAlreadyActive(msg) : .sessionNotActive(msg)
        case 429:
            if let obj = detail as? [String: Any],
               let cooldownData = try? JSONSerialization.data(withJSONObject: obj),
               let cd = try? decoder.decode(CooldownDetail.self, from: cooldownData) {
                throw BackendError.cooldown(cd)
            }
            throw BackendError.server(429, String(describing: detail))
        case 502:
            throw BackendError.routing(detail as? String ?? "routing error")
        default:
            throw BackendError.server(http.statusCode, String(describing: detail))
        }
    }
}
