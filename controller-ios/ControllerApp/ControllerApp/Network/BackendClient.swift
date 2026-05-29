import Foundation

struct BackendDevice: Codable, Sendable {
    let udid: String
    let name: String
    let boundClientId: String?

    enum CodingKeys: String, CodingKey {
        case udid, name
        case boundClientId = "bound_client_id"
    }
}

struct BackendLeader: Codable, Sendable, Identifiable {
    let clientId: String
    let name: String
    let state: String
    var id: String { clientId }

    enum CodingKeys: String, CodingKey {
        case clientId = "client_id"
        case name, state
    }
}

actor BackendClient {
    private var baseURL: URL
    private var deviceName: String?
    private var clientId: String?
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL, deviceName: String? = nil, clientId: String? = nil, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.deviceName = deviceName
        self.clientId = clientId
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
        // All models declare explicit CodingKeys — no global key strategy
        // so models with snake_case keys (e.g. CooldownDetail) decode uniformly
        // across the happy path and the error path.
    }

    func updateClientId(_ id: String?) {
        clientId = id
    }

    func updateBaseURL(_ url: URL) {
        baseURL = url
    }

    func updateDeviceName(_ name: String?) {
        deviceName = name
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

    func fetchDevices() async throws -> [BackendDevice] {
        try await getJSON("/api/devices", as: DevicesResponse.self).devices
    }

    func fetchLeaders() async throws -> [BackendLeader] {
        try await getJSON("/api/clients", as: LeadersResponse.self).clients
    }

    /// Binds this UUID to a device. Throws BackendError.duplicateClientId on 409.
    func bind(clientId: String, udid: String) async throws {
        _ = try await postJSON("/api/bind", body: BindBody(clientId: clientId, udid: udid), decode: Ok.self)
    }

    func follow(leaderClientId: String) async throws {
        guard let mine = clientId else { throw BackendError.routing("no client id set") }
        _ = try await postJSON("/api/follow",
                               body: FollowBody(followerClientId: mine, leaderClientId: leaderClientId),
                               decode: Ok.self)
    }

    func unfollow() async throws {
        guard let mine = clientId else { return }
        _ = try await postJSON("/api/unfollow", body: UnfollowBody(clientId: mine), decode: Ok.self)
    }

    func search(query: String, limit: Int = 8) async throws -> [SearchResult] {
        var comps = URLComponents(url: baseURL.appendingPathComponent("api/search"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        var req = URLRequest(url: comps.url!)
        applyDeviceHeader(&req)
        let (data, response) = try await session.data(for: req)
        try checkOk(response, data: data, isStart: false)
        return try decoder.decode(SearchResponse.self, from: data).results
    }

    // MARK: - private

    private struct Ok: Codable, Sendable { let ok: Bool }
    private struct OkReason: Codable, Sendable { let ok: Bool; let reason: String }
    private struct DevicesResponse: Decodable { let devices: [BackendDevice] }
    private struct BindBody: Encodable { let clientId: String; let udid: String
        enum CodingKeys: String, CodingKey { case clientId = "client_id"; case udid } }
    private struct FollowBody: Encodable { let followerClientId: String; let leaderClientId: String
        enum CodingKeys: String, CodingKey { case followerClientId = "follower_client_id"; case leaderClientId = "leader_client_id" } }
    private struct UnfollowBody: Encodable { let clientId: String
        enum CodingKeys: String, CodingKey { case clientId = "client_id" } }
    private struct LeadersResponse: Decodable { let clients: [BackendLeader] }

    private func applyDeviceHeader(_ req: inout URLRequest) {
        if let clientId {
            req.setValue(clientId, forHTTPHeaderField: "X-Client-Id")
        }
        if let name = deviceName {
            req.setValue(name, forHTTPHeaderField: "X-Device-Name")
        }
    }

    private func getJSON<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
        let url = baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        var req = URLRequest(url: url)
        applyDeviceHeader(&req)
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: false)
        return try decoder.decode(T.self, from: data)
    }

    private func postJSON<Body: Encodable, T: Decodable>(_ path: String, body: Body, decode: T.Type) async throws -> T {
        var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(body)
        applyDeviceHeader(&req)
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: path.hasSuffix("/session"), isBind: path.hasSuffix("/bind"))
        return try decoder.decode(T.self, from: data)
    }

    private func postEmpty(_ path: String) async throws -> Bool {
        var req = URLRequest(url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))))
        req.httpMethod = "POST"
        applyDeviceHeader(&req)
        let (data, resp) = try await session.data(for: req)
        try checkOk(resp, data: data, isStart: false)
        return (try? decoder.decode(Ok.self, from: data).ok) ?? true
    }

    private func checkOk(_ response: URLResponse, data: Data, isStart: Bool, isBind: Bool = false) throws {
        guard let http = response as? HTTPURLResponse else {
            throw BackendError.transport("non-HTTP response")
        }
        if (200..<300).contains(http.statusCode) { return }

        // Try to decode the FastAPI {"detail": ...} envelope.
        let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]

        switch http.statusCode {
        case 409:
            let msg = (detail as? String) ?? "conflict"
            if isBind { throw BackendError.duplicateClientId(msg) }
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
