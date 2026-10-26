#!/bin/bash
# ios-native-check. "compile" (default): TeleplyCore tests plus a simulator build, to catch compile errors fast.
# "shots": the same, then the screenshot tour on each simulator runtime in SHOT_RUNTIMES (default iOS 27.1;
# add iOS-26-5 at the end of a phase). Pictures land in build/shots.zip.
set -euo pipefail
source "$(dirname "$0")/ci-common.sh"

MODE="${1:-compile}"
RUNTIMES="${SHOT_RUNTIMES:-iOS-27-1}"
DEVICE="${SHOT_DEVICE:-iPhone 17}"

cd "$IOS_DIR"
mkdir -p build
generate_project
swift test --package-path TeleplyCore

if [ "$MODE" = compile ]; then
  xcodebuild build -project Teleply.xcodeproj -scheme Teleply -configuration Debug \
    -destination 'generic/platform=iOS Simulator' -derivedDataPath build/dd \
    COMPILER_INDEX_STORE_ENABLE=NO CODE_SIGNING_ALLOWED=NO | xcbeautify
  exit 0
fi

# Keep each result bundle for the artifacts even when a test fails.
pack_results() {
  for bundle in build/shots-*.xcresult; do
    [ -d "$bundle" ] && ditto -c -k --keepParent "$bundle" "$bundle.zip"
  done
  [ -d build/shots ] && (cd build && zip -qr shots.zip shots)
  return 0
}
trap pack_results EXIT

# The UDID of an available iPhone simulator on runtime $1: one the machine already has (preferring
# $DEVICE), else a new one of a device type that runtime says it supports. Build #4 showed that a fixed
# "iPhone 17" is refused on iOS 27.1 ("Incompatible device").
pick_device() {
  python3 - "$1" "$DEVICE" <<'PY'
import json, subprocess, sys
key, preferred = sys.argv[1], sys.argv[2]
runtime_id = "com.apple.CoreSimulator.SimRuntime." + key
def simctl(*args):
    return json.loads(subprocess.check_output(["xcrun", "simctl", "list", *args, "-j"]))
phones = [d for d in simctl("devices", "available")["devices"].get(runtime_id, []) if d["name"].startswith("iPhone")]
if phones:
    choice = next((d for d in phones if d["name"] == preferred), phones[0])
    sys.stderr.write("Using simulator %s (%s) on %s\n" % (choice["name"], choice["udid"], key))
    print(choice["udid"])
    sys.exit(0)
runtimes = simctl("runtimes")["runtimes"]
types = next((r.get("supportedDeviceTypes", []) for r in runtimes if r["identifier"] == runtime_id), [])
kinds = [t for t in types if t["name"].startswith("iPhone")]
if not kinds:
    sys.stderr.write("No iPhone simulator for %s. Runtimes here: %s\n" % (runtime_id, ", ".join(r["identifier"] for r in runtimes)))
    sys.exit(1)
kind = next((t for t in kinds if t["name"] == preferred), kinds[0])
sys.stderr.write("Creating simulator %s on %s (supported: %s)\n" % (kind["name"], key, ", ".join(t["name"] for t in kinds)))
print(subprocess.check_output(["xcrun", "simctl", "create", "shots-" + key, kind["identifier"], runtime_id]).decode().strip())
PY
}

xcodebuild build-for-testing -project Teleply.xcodeproj -scheme Teleply -configuration Debug \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build/dd \
  COMPILER_INDEX_STORE_ENABLE=NO | xcbeautify
XCTESTRUN=$(ls build/dd/Build/Products/*.xctestrun | head -n 1)

rm -rf build/shots && mkdir -p build/shots
for runtime in $RUNTIMES; do
  udid=$(pick_device "$runtime")
  xcrun simctl boot "$udid" 2>/dev/null || true  # already booted is fine
  xcrun simctl bootstatus "$udid" -b
  xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 || true
  TEST_RUNNER_SHOTS_DIR="$IOS_DIR/build/shots" xcodebuild test-without-building \
    -xctestrun "$XCTESTRUN" -destination "id=$udid" \
    -only-testing:TeleplyUITests/ScreenshotTour \
    -resultBundlePath "build/shots-$runtime.xcresult" | xcbeautify
  xcrun simctl shutdown "$udid" || true
done
ls -1 build/shots
