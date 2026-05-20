import SwiftUI

struct SettingsScreen: View {
    @Binding var config: BackendConfig
    let client: BackendClient
    @State private var urlText: String = ""
    @State private var saving: Bool = false
    @State private var probeMessage: String? = nil
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Backend") {
                    TextField("http://host:port", text: $urlText)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button(saving ? "Testing…" : "Test connection") {
                        Task { await probe() }
                    }
                    .disabled(saving)
                    if let m = probeMessage {
                        Text(m).font(.caption)
                    }
                }
                Section("Build") {
                    Text("ControllerApp · iOS 17+").font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        if let url = URL(string: urlText) {
                            config = BackendConfig(baseURL: url)
                            config.save()
                            Task { await client.updateBaseURL(url) }
                            dismiss()
                        } else {
                            probeMessage = "Invalid URL"
                        }
                    }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .onAppear { urlText = config.baseURL.absoluteString }
        }
    }

    private func probe() async {
        guard let url = URL(string: urlText) else { probeMessage = "Invalid URL"; return }
        saving = true; defer { saving = false }
        let tester = BackendClient(baseURL: url)
        do {
            let snap = try await tester.fetchStatus()
            probeMessage = "OK — state: \(snap.state.rawValue)"
        } catch {
            probeMessage = "Failed: \(error)"
        }
    }
}
