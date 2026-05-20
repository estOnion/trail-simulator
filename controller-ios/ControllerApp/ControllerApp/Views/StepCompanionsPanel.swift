import SwiftUI

struct StepCompanionsPanel: View {
    @EnvironmentObject var store: SessionStore

    var body: some View {
        let companions = store.latest?.stepCompanions ?? []
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Image(systemName: "shoeprints.fill")
                Text("Step companions").font(.headline)
                Spacer()
                Text("\(companions.count)").foregroundStyle(.secondary).monospacedDigit()
            }
            if companions.isEmpty {
                Text("No step companions connected.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(companions) { c in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(c.label).font(.subheadline)
                            if let udid = c.udid {
                                Text(udid).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                            }
                        }
                        Spacer()
                        Text("\(c.totalAcked) steps").font(.caption).monospacedDigit()
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .padding(10)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }
}
