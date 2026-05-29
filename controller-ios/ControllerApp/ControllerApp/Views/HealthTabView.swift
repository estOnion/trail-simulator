import SwiftUI

struct HealthTabView: View {
    @EnvironmentObject var health: HealthStore
    @ObservedObject private var writerProxy: HealthWriter
    @ObservedObject private var clientProxy: StepClient

    init(health: HealthStore) {
        _writerProxy = ObservedObject(wrappedValue: health.writer)
        _clientProxy = ObservedObject(wrappedValue: health.client)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("HealthKit") {
                    HStack {
                        Circle()
                            .fill(writerProxy.authorized ? .green : .red)
                            .frame(width: 10, height: 10)
                        Text(writerProxy.authorized ? "Granted" : "Pending")
                    }
                    if !writerProxy.authorized {
                        Button("Request HealthKit permission") {
                            Task { await writerProxy.requestAuthorization() }
                        }
                    }
                }

                Section("Step writing") {
                    Toggle("Write steps to HealthKit", isOn: $health.enabled)
                        .disabled(!writerProxy.authorized)
                    HStack {
                        Circle()
                            .fill(clientProxy.connected ? .green : .gray)
                            .frame(width: 8, height: 8)
                        Text(clientProxy.connected ? "Connected to /ws/steps" : "Disconnected")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("This session") {
                    LabeledContent("Steps", value: "\(health.sessionSteps)")
                    LabeledContent("Distance",
                                   value: String(format: "%.1f m", health.sessionDistanceM))
                }

                Section("Cumulative") {
                    LabeledContent("Steps", value: "\(health.cumulativeSteps)")
                    LabeledContent("Distance",
                                   value: String(format: "%.1f m", health.cumulativeDistanceM))
                }

                if let err = clientProxy.lastError ?? writerProxy.lastError {
                    Section("Error") {
                        Text(err).foregroundStyle(.red).font(.caption)
                    }
                }
            }
            .navigationTitle("Health")
        }
    }
}
