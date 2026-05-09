// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "NumBridgeLauncher",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "NumBridgeLauncher",
            path: "Sources/NumBridgeLauncher"
        )
    ]
)
