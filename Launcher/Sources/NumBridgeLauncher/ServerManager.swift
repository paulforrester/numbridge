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
    /// Covers port-clearing → process spawn → HTTP readiness polling as one unit.
    private var launchTask: Task<Void, Never>?
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
        beginLaunch()
    }

    func stop() {
        shouldAutoRestart = false
        restartTask?.cancel(); restartTask = nil
        launchTask?.cancel();  launchTask  = nil

        guard let proc = process, proc.isRunning else {
            process = nil
            status = .stopped
            return
        }

        process = nil
        proc.terminate()

        let grace = Self.shutdownGrace
        DispatchQueue.global().asyncAfter(deadline: .now() + grace) {
            if proc.isRunning { kill(proc.processIdentifier, SIGKILL) }
        }

        status = .stopped
    }

    // MARK: - Launch pipeline

    /// Single task that: clears any stale port holder → spawns → polls readiness.
    private func beginLaunch() {
        guard let serverDir = resolveServerDir() else {
            status = .error("Server directory not found — set NUMBRIDGE_SERVER_DIR")
            return
        }
        guard let uv = findUV() else {
            status = .error("'uv' not found — install from https://docs.astral.sh/uv/")
            return
        }

        let port = self.port

        launchTask?.cancel()
        launchTask = Task {
            // Step 1 — kill any orphaned server still holding our port
            // (happens when the launcher app is force-quit leaving uvicorn running)
            let stale = await Task.detached(priority: .utility) {
                Self.pidsListeningOnPort(port)
            }.value

            if !stale.isEmpty {
                self.log.info("Clearing stale server on port \(port), PIDs: \(stale)")
                stale.forEach { kill($0, SIGTERM) }
                try? await Task.sleep(for: .seconds(1))
                stale.forEach { kill($0, SIGKILL) }          // force-kill survivors
                try? await Task.sleep(for: .milliseconds(300)) // let the OS free the port
            }

            guard !Task.isCancelled else { return }

            // Step 2 — spawn the server process
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: uv)
            proc.arguments = ["run", "python", "-m", "numbridge"]
            proc.currentDirectoryURL = serverDir
            proc.environment = self.enrichedEnvironment()
            self.redirectOutput(proc)

            proc.terminationHandler = { [weak self] p in
                Task { @MainActor [weak self] in
                    self?.handleExit(code: p.terminationStatus)
                }
            }

            do {
                try proc.run()
            } catch {
                self.status = .error(error.localizedDescription)
                self.log.error("Failed to launch: \(error)")
                return
            }

            self.process = proc
            self.log.info("Server started (PID \(proc.processIdentifier), port \(port))")

            guard !Task.isCancelled else { return }

            // Step 3 — poll until uvicorn accepts HTTP connections
            let url = URL(string: "http://127.0.0.1:\(port)/mcp")!
            var request = URLRequest(url: url, timeoutInterval: 1.5)
            request.httpMethod = "GET"
            let session = URLSession(configuration: .ephemeral)

            let deadline = ContinuousClock.now + Self.readyTimeout
            while ContinuousClock.now < deadline {
                try? await Task.sleep(for: Self.readyPollInterval)
                guard !Task.isCancelled else { return }

                if let _ = try? await session.data(for: request) {
                    self.status = .running(pid: proc.processIdentifier, port: port)
                    self.log.info("Server ready on port \(port)")
                    return
                }
            }

            self.log.error("Server did not become ready within 15 s")
            self.status = .error("Did not become ready — restarting…")
            proc.terminate()
            self.process = nil
        }
    }

    private func handleExit(code: Int32) {
        launchTask?.cancel()
        launchTask = nil
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
            self.beginLaunch()
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

    /// Ordered search: user-local installs first, then system paths.
    /// Explicit paths required because macOS GUI apps don't inherit the shell PATH.
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
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        env["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:\(env["PATH"] ?? "/usr/bin:/bin")"
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

    // MARK: - Port utilities (nonisolated — safe to call from background threads)

    /// Returns PIDs of all processes with a TCP LISTEN socket on `port`.
    /// Runs synchronously; call from a background thread or detached Task.
    nonisolated private static func pidsListeningOnPort(_ port: Int) -> [Int32] {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        proc.arguments = ["-t", "-i", "TCP:\(port)", "-sTCP:LISTEN"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        guard (try? proc.run()) != nil else { return [] }
        proc.waitUntilExit()
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return out
            .components(separatedBy: .newlines)
            .compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }
            .filter { $0 > 0 }
    }
}
