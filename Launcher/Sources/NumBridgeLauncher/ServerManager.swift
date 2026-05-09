import Foundation
import Combine
import os.log

enum ServerStatus: Equatable {
    case stopped
    case starting
    case running(pid: Int32)
    case error(String)
}

/// Owns the Python MCP server subprocess lifecycle: launch, monitor, auto-restart, shutdown.
@MainActor
class ServerManager: ObservableObject {
    @Published private(set) var status: ServerStatus = .stopped

    private var process: Process?
    private var restartTask: Task<Void, Never>?
    private var shouldAutoRestart = false

    private static let restartDelay: Duration = .seconds(3)
    private static let shutdownGrace: TimeInterval = 2.0

    private let log = Logger(subsystem: "com.numbridge.launcher", category: "server")

    // MARK: - Public

    func start() {
        guard case .stopped = status else { return }
        shouldAutoRestart = true
        status = .starting
        launch()
    }

    func stop() {
        shouldAutoRestart = false
        restartTask?.cancel()
        restartTask = nil

        guard let proc = process, proc.isRunning else {
            process = nil
            status = .stopped
            return
        }

        // Clear self.process before terminate so the termination handler won't reschedule
        process = nil
        proc.terminate()

        // Force-kill after grace period if still alive
        let shutdownGrace = Self.shutdownGrace
        DispatchQueue.global().asyncAfter(deadline: .now() + shutdownGrace) {
            if proc.isRunning {
                kill(proc.processIdentifier, SIGKILL)
            }
        }

        status = .stopped
    }

    // MARK: - Private

    private func launch() {
        guard let serverDir = resolveServerDir() else {
            status = .error("Server directory not found — set NUMBRIDGE_SERVER_DIR")
            log.error("Could not locate server directory")
            return
        }

        guard let uv = findExecutable("uv") else {
            status = .error("'uv' not found — install from https://docs.astral.sh/uv/")
            log.error("uv executable not found")
            return
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: uv)
        proc.arguments = ["run", "python", "-m", "numbridge"]
        proc.currentDirectoryURL = serverDir
        proc.environment = enrichedEnvironment()

        redirectOutput(proc)

        proc.terminationHandler = { [weak self] p in
            Task { @MainActor [weak self] in
                self?.handleExit(code: p.terminationStatus)
            }
        }

        do {
            try proc.run()
            process = proc
            status = .running(pid: proc.processIdentifier)
            log.info("Server started (PID \(proc.processIdentifier))")
        } catch {
            status = .error(error.localizedDescription)
            log.error("Failed to launch: \(error)")
        }
    }

    private func handleExit(code: Int32) {
        process = nil

        guard shouldAutoRestart else {
            status = .stopped
            return
        }

        log.warning("Server exited (code \(code)) — restarting in \(Self.restartDelay)")
        status = .error("Exited (code \(code)) — restarting…")

        restartTask = Task {
            try? await Task.sleep(for: Self.restartDelay)
            guard !Task.isCancelled else { return }
            self.status = .starting
            self.launch()
        }
    }

    // MARK: - Path resolution

    /// Lookup order:
    ///   1. NUMBRIDGE_SERVER_DIR env var (dev override)
    ///   2. <AppBundle>/Contents/Resources/server/ (production bundle)
    ///   3. Sibling to the .app bundle — dist/server/ symlink created by `make bundle`
    private func resolveServerDir() -> URL? {
        if let envPath = ProcessInfo.processInfo.environment["NUMBRIDGE_SERVER_DIR"] {
            return URL(fileURLWithPath: envPath)
        }

        if let resources = Bundle.main.resourceURL {
            let candidate = resources.appendingPathComponent("server")
            if FileManager.default.fileExists(atPath: candidate.path) { return candidate }
        }

        let sibling = Bundle.main.bundleURL
            .deletingLastPathComponent()
            .appendingPathComponent("server")
        if FileManager.default.fileExists(atPath: sibling.path) { return sibling }

        return nil
    }

    private func findExecutable(_ name: String) -> String? {
        ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
            .map { "\($0)/\(name)" }
            .first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private func enrichedEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:\(env["PATH"] ?? "/usr/bin:/bin")"
        return env
    }

    private func redirectOutput(_ proc: Process) {
        guard let logURL = logFileURL() else { return }
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        guard let handle = try? FileHandle(forWritingTo: logURL) else { return }
        proc.standardOutput = handle
        proc.standardError = handle
    }

    private func logFileURL() -> URL? {
        guard let logDir = FileManager.default
            .urls(for: .libraryDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent("Logs/NumBridge")
        else { return nil }
        try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
        return logDir.appendingPathComponent("server.log")
    }
}
