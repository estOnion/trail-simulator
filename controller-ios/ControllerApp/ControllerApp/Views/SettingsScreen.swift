import SwiftUI

struct SettingsScreen: View {
    @Binding var config: BackendConfig
    let client: BackendClient
    @EnvironmentObject var store: SessionStore
    @State private var urlText: String = ""
    @State private var saving: Bool = false
    @State private var probeMessage: ProbeMessage? = nil
    @State private var devices: [BackendDevice] = []
    @State private var loadingDevices: Bool = false
    @State private var deviceError: String? = nil
    @FocusState private var urlFocused: Bool

    private enum ProbeMessage: Equatable {
        case ok(String)
        case info(String)
        case failure(String)

        var text: String {
            switch self {
            case .ok(let s), .info(let s), .failure(let s): return s
            }
        }
        var isError: Bool {
            if case .failure = self { return true }
            return false
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Backend") {
                    TextField("http://host:port", text: $urlText)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($urlFocused)
                        .submitLabel(.done)
                        .onSubmit { save() }

                    Button(saving ? "Testing…" : "Test connection") {
                        urlFocused = false
                        Task { await probe() }
                    }
                    .disabled(saving)

                    if let m = probeMessage {
                        Text(m.text)
                            .font(.caption)
                            .foregroundStyle(m.isError ? .red : .secondary)
                    }
                }

                Section("Device") {
                    if loadingDevices {
                        HStack { ProgressView(); Text("Loading devices…").font(.subheadline) }
                    } else if devices.isEmpty {
                        Text(deviceError ?? "No devices found. Test the connection above, then refresh.")
                            .font(.caption)
                            .foregroundStyle(deviceError == nil ? Color.secondary : Color.red)
                    } else {
                        Picker("This iPhone", selection: deviceSelection) {
                            ForEach(devices, id: \.udid) { d in
                                Text(d.name).tag(Optional(d.name))
                            }
                        }
                    }
                    Button("Refresh devices") {
                        urlFocused = false
                        Task { await loadDevices() }
                    }
                    .disabled(loadingDevices)
                }

                Section("Connection") {
                    HStack {
                        Circle()
                            .fill(store.isConnected ? .green : .secondary)
                            .frame(width: 8, height: 8)
                        Text(store.isConnected ? "Connected" : "Disconnected")
                            .font(.subheadline)
                        Spacer()
                    }
                    Button(store.isConnected ? "Disconnect" : "Connect") {
                        store.isConnected.toggle()
                    }
                    .tint(store.isConnected ? .red : .accentColor)
                }

                Section("Build") {
                    Text("ControllerApp · iOS 17+").font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        urlText = config.baseURL.absoluteString
                        urlFocused = false
                        probeMessage = .info("Changes reverted")
                    }
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { urlFocused = false }
                }
            }
            .onAppear { urlText = config.baseURL.absoluteString }
            .task { await loadDevices() }
        }
    }

    private var deviceSelection: Binding<String?> {
        Binding(
            get: { config.deviceName },
            set: { newValue in
                config.deviceName = newValue
                config.save()
            }
        )
    }

    private func loadDevices() async {
        loadingDevices = true
        deviceError = nil
        defer { loadingDevices = false }
        do {
            let found = try await client.fetchDevices()
            devices = found
            // Auto-select the only device, or drop a stale selection that the
            // backend no longer knows about (would otherwise route nowhere).
            if found.count == 1 {
                if config.deviceName != found[0].name {
                    config.deviceName = found[0].name
                    config.save()
                }
            } else if let current = config.deviceName,
                      !found.contains(where: { $0.name == current }) {
                config.deviceName = nil
                config.save()
            }
        } catch {
            devices = []
            deviceError = "Can't load devices — check the backend URL and connection."
        }
    }

    private func save() {
        guard let url = URL(string: urlText), url.scheme != nil, url.host != nil else {
            probeMessage = .failure("Invalid URL — must include scheme and host (e.g. http://192.168.1.50:8080)")
            return
        }
        config.baseURL = url
        config.save()
        urlFocused = false
        probeMessage = .ok("Saved ✓")
        Task {
            await client.updateBaseURL(url)
            await loadDevices()
        }
    }

    private func probe() async {
        guard let url = URL(string: urlText), url.scheme != nil, url.host != nil else {
            probeMessage = .failure("Invalid URL")
            return
        }
        saving = true; defer { saving = false }
        let tester = BackendClient(baseURL: url)
        do {
            let snap = try await tester.fetchStatus()
            probeMessage = .ok("OK — state: \(snap.state.rawValue)")
            await loadDevices()
        } catch let BackendError.transport(msg) {
            probeMessage = .failure("Can't reach backend — \(friendlyTransport(msg))")
        } catch let BackendError.server(code, _) {
            probeMessage = .failure("Backend error (HTTP \(code))")
        } catch let BackendError.routing(msg) {
            probeMessage = .failure("Routing error — \(msg)")
        } catch let urlErr as URLError {
            probeMessage = .failure("Can't reach backend — \(friendlyURLError(urlErr))")
        } catch {
            probeMessage = .failure("Connection failed")
        }
    }

    private func friendlyTransport(_ msg: String) -> String {
        msg.isEmpty ? "no response" : msg
    }

    private func friendlyURLError(_ e: URLError) -> String {
        switch e.code {
        case .cannotConnectToHost: return "host refused connection"
        case .cannotFindHost:      return "host not found"
        case .timedOut:            return "request timed out"
        case .notConnectedToInternet: return "no network"
        default: return e.localizedDescription
        }
    }
}
