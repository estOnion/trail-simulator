import SwiftUI

struct FollowSheet: View {
    let client: BackendClient
    @EnvironmentObject var store: SessionStore
    @Environment(\.dismiss) private var dismiss

    @State private var leaders: [BackendLeader] = []
    @State private var loading = false
    @State private var pasteText = ""
    @State private var selectedId: String? = nil
    @State private var mirrorGPS = false
    @State private var errorText: String? = nil
    @State private var working = false

    private var chosenLeaderId: String? {
        let pasted = pasteText.trimmingCharacters(in: .whitespaces)
        return pasted.isEmpty ? selectedId : pasted
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Active leaders") {
                    if loading {
                        HStack { ProgressView(); Text("Loading…") }
                    } else if leaders.isEmpty {
                        Text("No active leaders found.").font(.caption).foregroundStyle(.secondary)
                    } else {
                        Picker("Leader", selection: $selectedId) {
                            Text("None").tag(String?.none)
                            ForEach(leaders) { l in
                                Text("\(l.name) · \(l.state)").tag(Optional(l.clientId))
                            }
                        }
                    }
                    Button("Refresh") { Task { await load() } }.disabled(loading)
                }

                Section("Or paste a UUID") {
                    TextField("leader UUID", text: $pasteText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    Toggle("Mirror onto this phone (GPS)", isOn: $mirrorGPS)
                    Text(mirrorGPS
                         ? "This phone's GPS will track the leader's route."
                         : "Watch the leader on the map only; this phone is unaffected.")
                        .font(.caption).foregroundStyle(.secondary)
                }

                if let errorText {
                    Section { Text(errorText).font(.caption).foregroundStyle(.red) }
                }

                Section {
                    Button(working ? "Starting…" : "Start following") {
                        Task { await startFollowing() }
                    }
                    .disabled(working || chosenLeaderId == nil)
                }
            }
            .navigationTitle("Follow a leader")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task { await load() }
        }
    }

    private func load() async {
        loading = true; defer { loading = false }
        leaders = (try? await client.fetchLeaders()) ?? []
    }

    private func startFollowing() async {
        guard let leaderId = chosenLeaderId else { return }
        working = true; errorText = nil; defer { working = false }
        if mirrorGPS {
            do {
                try await client.follow(leaderClientId: leaderId)
                store.watchingLeaderId = nil
                dismiss()
            } catch {
                errorText = "Couldn't start GPS follow — check the leader UUID."
            }
        } else {
            store.watchingLeaderId = leaderId
            dismiss()
        }
    }
}
