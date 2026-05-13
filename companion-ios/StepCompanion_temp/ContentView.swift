import SwiftUI

struct ContentView: View {
    @EnvironmentObject var writer: HealthWriter
    @StateObject private var client = StepClient()

    @State private var hostText = "192.168.1.x"
    @State private var portText = "8787"

    private var wsURL: URL? {
        URL(string: "ws://\(hostText):\(portText)/ws/steps")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Backend") {
                    TextField("Host", text: $hostText)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                    TextField("Port", text: $portText)
                        .keyboardType(.numberPad)
                }

                Section("Connection") {
                    HStack {
                        Circle()
                            .fill(client.connected ? Color.green : Color.red)
                            .frame(width: 10, height: 10)
                        Text(client.connected ? "Connected" : "Disconnected")
                    }
                    Button(client.connected ? "Disconnect" : "Connect") {
                        if client.connected {
                            client.disconnect()
                        } else if let url = wsURL {
                            client.connect(url: url, writer: writer)
                        }
                    }
                    .disabled(!writer.authorized && !client.connected)
                }

                Section("Stats") {
                    LabeledContent("Steps written", value: "\(client.totalWritten)")
                    LabeledContent("HealthKit auth", value: writer.authorized ? "granted" : "pending")
                }

                Section("Debug") {
                    Button("Write 100 steps now") {
                        Task { await writer.writeDebugSample() }
                    }
                    .disabled(!writer.authorized)
                }

                if let err = client.lastError ?? writer.lastError {
                    Section("Error") {
                        Text(err).foregroundStyle(.red).font(.caption)
                    }
                }
            }
            .navigationTitle("Step Companion")
        }
    }
}
