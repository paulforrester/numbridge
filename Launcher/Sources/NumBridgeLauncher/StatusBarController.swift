import AppKit
import Combine

/// Owns the NSStatusItem and rebuilds the menu whenever ServerManager.status changes.
@MainActor
class StatusBarController {
    private let item: NSStatusItem
    private let server: ServerManager
    private var cancellables = Set<AnyCancellable>()

    init(server: ServerManager) {
        self.server = server
        self.item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)

        server.$status
            .receive(on: DispatchQueue.main)
            .sink { [weak self] in self?.apply($0) }
            .store(in: &cancellables)
    }

    // MARK: - Status updates

    private func apply(_ status: ServerStatus) {
        guard let button = item.button else { return }

        switch status {
        case .stopped:
            button.image = symbol("tablecells", label: "NumBridge: Stopped")
            button.appearsDisabled = true
        case .starting:
            button.image = symbol("tablecells", label: "NumBridge: Starting")
            button.appearsDisabled = false
        case .running:
            button.image = symbol("tablecells.fill", label: "NumBridge: Running")
            button.appearsDisabled = false
        case .error:
            button.image = symbol("exclamationmark.triangle.fill", label: "NumBridge: Error")
            button.appearsDisabled = false
        }

        item.menu = buildMenu(status)
    }

    // MARK: - Menu construction

    private func buildMenu(_ status: ServerStatus) -> NSMenu {
        let menu = NSMenu()

        let header = NSMenuItem(title: headerTitle(status), action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(.separator())

        switch status {
        case .running:
            menu.addItem(menuItem("Stop Server", action: #selector(stopServer)))
        case .stopped, .error:
            menu.addItem(menuItem("Start Server", action: #selector(startServer)))
        case .starting:
            let item = NSMenuItem(title: "Starting…", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }

        menu.addItem(menuItem("Show Log", action: #selector(showLog)))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit NumBridge",
                                action: #selector(NSApplication.terminate(_:)),
                                keyEquivalent: "q"))
        return menu
    }

    private func headerTitle(_ status: ServerStatus) -> String {
        switch status {
        case .stopped:           return "NumBridge — Stopped"
        case .starting:          return "NumBridge — Starting…"
        case .running(let pid):  return "NumBridge — Running  (PID \(pid))"
        case .error(let msg):    return "NumBridge — \(msg)"
        }
    }

    // MARK: - Actions

    @objc private func startServer() { server.start() }
    @objc private func stopServer()  { server.stop() }

    @objc private func showLog() {
        let url = FileManager.default
            .urls(for: .libraryDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent("Logs/NumBridge/server.log")
        if let url { NSWorkspace.shared.open(url) }
    }

    // MARK: - Helpers

    private func menuItem(_ title: String, action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        return item
    }

    private func symbol(_ name: String, label: String) -> NSImage? {
        let img = NSImage(systemSymbolName: name, accessibilityDescription: label)
        img?.isTemplate = true  // renders correctly in both light/dark menu bar
        return img
    }
}
