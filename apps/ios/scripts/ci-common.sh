#!/bin/bash
# Shared by the Codemagic workflows in codemagic.yaml: a fixed XcodeGen release, checked against GitHub's
# SHA-256, turns project.yml into Teleply.xcodeproj.
set -euo pipefail

IOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XCODEGEN_VERSION=2.46.0
XCODEGEN_SHA256=4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806

generate_project() {
  local tools="$IOS_DIR/build/tools" binary
  binary=$(find "$tools" -type f -name xcodegen 2>/dev/null | head -n 1 || true)
  if [ -z "$binary" ]; then
    mkdir -p "$tools"
    curl -fsSL -o "$tools/xcodegen.zip" "https://github.com/yonaskolb/XcodeGen/releases/download/$XCODEGEN_VERSION/xcodegen.zip"
    echo "$XCODEGEN_SHA256  $tools/xcodegen.zip" | shasum -a 256 -c -
    unzip -q -o "$tools/xcodegen.zip" -d "$tools"
    binary=$(find "$tools" -type f -name xcodegen | head -n 1)
    chmod +x "$binary"
  fi
  "$binary" generate --spec "$IOS_DIR/project.yml" --project "$IOS_DIR"
  xcodebuild -version
}
