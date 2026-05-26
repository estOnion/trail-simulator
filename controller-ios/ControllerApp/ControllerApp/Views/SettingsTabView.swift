import SwiftUI

struct SettingsTabView: View {
    @Binding var config: BackendConfig
    let client: BackendClient

    var body: some View {
        SettingsScreen(config: $config, client: client)
    }
}
