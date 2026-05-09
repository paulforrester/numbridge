import SwiftUI
import ServiceManagement

@main
struct NumBridgeLauncherApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate

    var body: some Scene {
        // No windows — this is a menu-bar-only app (LSUIElement = true)
        Settings { EmptyView() }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusBar: StatusBarController?
    private var server: ServerManager?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let server = ServerManager()
        self.server = server
        self.statusBar = StatusBarController(server: server)

        registerLoginItem()
        server.start()
    }

    func applicationWillTerminate(_ notification: Notification) {
        server?.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    private func registerLoginItem() {
        guard SMAppService.mainApp.status == .notRegistered else { return }
        do {
            try SMAppService.mainApp.register()
        } catch {
            // Non-fatal: fails gracefully outside a signed app bundle.
            // User can add via System Settings → General → Login Items.
        }
    }
}
