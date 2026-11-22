import GoogleMobileAds
import SwiftUI

@main
struct ColorMixNaviApp: App {
    @StateObject private var pro = ProStore()

    init() {
        MobileAds.shared.start()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(pro)
                .task { await pro.load() }
                .preferredColorScheme(.light)
        }
    }
}
