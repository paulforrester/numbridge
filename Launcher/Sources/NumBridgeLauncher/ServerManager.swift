import Foundation
import Combine
import os.log

enum ServerStatus: Equatable {
    case stopped
    case starting
    case running(pid: Int32, port: Int)
    case error(String)
}

/// Owns the Python MCP server subprocess lifecycle: launch, HTTP-readiness check,
/// auto-restart on unexpected exit, and graceful shutdown.
@MainActor
class ServerManager: ObservableObject {
    @Published private(set) var status: ServerStatus = .stopped

    private var process: Process?
    private var restartTask: Task<Void, Never>?
    private var healthCheckTask: Task<Void, Never>?
    private var shouldAutoRestart = false

    /// Port the Python server listens on. Override with NUMBRIDGE_PORT env var.
    let port: Int = {
        if let s = ProcessInfo.processInfo.environment["NUMBRIDGE_PORT"], let n = Int(s) { return n }
        return 8765
    }()

    private static let restartDelay: Duration = .seconds(3)
    private static let shutdownGrace: TimeInterval = 2.0
    private static let readyPollInterval: Duration = .milliseconds(400)
    private static let readyTimeout: Duration = .seconds(15)

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
        healthCheckTask?.cancel()
        healthCheckTask = nil

        guard let proc = process, proc.isRunning else {
            process = nil
            status = .stopped
            return
        }

        // Clear before terminate so terminationHandler won't schedule a restart
        process = nil
        proc.terminate()

        let grace = Self.shutdownGrace
        DispatchQueue.global().asyncAfter(deadline: .now() + grace) {
            if proc.isRunning { kill(proc.processIdentifier, SIGKILL) }
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

        guard let uv = findUV() else {
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
            log.info("Server process started (PID \(proc.processIdentifier), port \(self.port))")
            beginHealthCheck(pid: proc.processIdentifier)
        } catch {
            status = .error(error.localizedDescription)
            log.error("Failed to launch: \(error)")
        }
    }

    private func handleExit(code: Int32) {
        healthCheckTask?.cancel()
        healthCheckTask = nil
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

    // MARK: - HTTP readiness poll

    /// Polls GET /mcp until any HTTP response arrives (even 406 = server up) or timeout.
    private func beginHealthCheck(pid: Int32) {
        let port = self.port
        let url = URL(string: "http://127.0.0.1:\(port)/mcp")!
        var request = URLRequest(url: url, timeoutInterval: 1.5)
        request.httpMethod = "GET"

        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 1.5
        let session = URLSession(configuration: config)

        healthCheckTask = Task {
            let deadline = ContinuousClock.now + Self.readyTimeout
            while ContinuousClock.now < deadline {
                try? await Task.sleep(for: Self.readyPollInterval)
                guard !Task.isCancelled else { return }

                if let _ = try? await session.data(for: request) {
                    // Any HTTP response means uvicorn is accepting connections
                    self.status = .running(pid: pid, port: port)
                    self.log.info("Server ready on port \(port)")
                    return
                }
            }
            // Timed out waiting for readiness — kill and let restart logic handle it
            self.log.error("Server readiness timeout after 15s")
            self.status = .error("Did not become ready — restarting…")
            self.process?.terminate()
        }
    }

    // MARK: - Path resolution

    /// Lookup order:
    ///   1. NUMBRIDGE_SERVER_DIR env var
    ///   2. <AppBundle>/Contents/Resources/server/
    ///   3. Sibling to .app bundle — dist/server symlink created by `make bundle`
    private func resolveServerDir() -> URL? {
        if let env = ProcessInfo.processInfo.environment["NUMBRIDGE_SERVER_DIR"] {
            return URL(fileURLWithPath: env)
        }
        if let res = Bundle.main.resourceURL {
            let c = res.appendingPathComponent("server")
            if FileManager.default.fileExists(atPath: c.path) { return c }
        }
        let sibling = Bundle.main.bundleURL
            .deletingLastPathComponent()
            .appendingPathComponent("server")
        if FileManager.default.fileExists(atPath: sibling.path) { return sibling }
        return nil
    }

    /// Ordered search: user-local installs first, then system Homebrew paths.
    private func findUV() -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let candidates = [
            "\(home)/.local/bin/uv",
            "\(home)/.cargo/bin/uv",
            "/opt/homebrew/bin/uv",
            "/usr/local/bin/uv",
        ]
        if let found = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) {
            return found
        }
        return resolveViaEnv("uv")
    }

    private func resolveViaEnv(_ name: String) -> String? {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["which", name]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        guard (try? proc.run()) != nil else { return nil }
        proc.waitUntilExit()
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return out?.isEmpty == false ? out : nil
    }

    private func enrichedEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "\(FileManager.default.homeDirectoryForCurrentUser.path)/.local/bin:/opt/homebrew/bin:/usr/local/bin:\(env["PATH"] ?? "/usr/bin:/bin")"
        env["NUMBRIDGE_PORT"] = String(port)
        return env
    }

    private func redirectOutput(_ proc: Process) {
        guard let url = logFileURL() else { return }
        FileManager.default.createFile(atPath: url.path, contents: nil)
        guard let handle = try? FileHandle(forWritingTo: url) else { return }
        proc.standardOutput = handle
        proc.standardError = handle
    }

    private func logFileURL() -> URL? {
        guard let dir = FileManager.default
            .urls(for: .libraryDirectory, in: .userDomainMask).first?
            .appendingPathComponent("Logs/NumBridge")
        else { return nil }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("server.log")
    }
}
