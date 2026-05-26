import SwiftUI

struct StepCompanionsPanel: View {
    @EnvironmentObject var health: HealthStore

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "iphone.gen3")
            VStack(alignment: .leading, spacing: 2) {
                Text("This Device").font(.subheadline).bold()
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text("\(health.sessionSteps) steps")
                .font(.caption).monospacedDigit()
        }
        .padding(10)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }

    private var subtitle: String {
        if !health.writer.authorized { return "HealthKit not granted" }
        return health.enabled ? "Writes enabled" : "Writes off"
    }
}
