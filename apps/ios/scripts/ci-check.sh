#!/bin/bash
# ios-native-check. "compile" (default): TeleplyCore tests plus a simulator build, to catch compile errors fast.
# "shots": the same, then the screenshot tour on each simulator runtime in SHOT_RUNTIMES (default iOS 26.5;
# add iOS-27-1 at the end of a phase) on a 6.9-inch iPhone, the size App Store Connect asks for. Pictures land in
# build/shots.zip. A failed test does not wait for the simulator's diagnostics (they took 10 minutes in build 6adede40).
set -euo pipefail
source "$(dirname "$0")/ci-common.sh"

MODE="${1:-compile}"
# iOS 26.5 by default: on this Xcode 27.1 image the 27.1 runtime only supports the foldable iPhone Duo, whose
# side column moves the navigation bar (builds 6aded501, 6adeda5d). Add iOS-27-1 at the end of a phase.
RUNTIMES="${SHOT_RUNTIMES:-iOS-26-5}"
# The iPhone 17 Pro Max (6.9 inch, 1320 x 2868) by default: App Store screenshots must come from a 6.9-inch phone.
# Where a runtime has none, pick_device takes another Pro Max, then an ordinary phone with a warning.
DEVICE="${SHOT_DEVICE:-iPhone 17 Pro Max}"
# SHOT_ONLY: some of the tour's variants, e.g. "testLight testLargestText", to save build minutes after a small fix.
ONLY=()
for test in ${SHOT_ONLY:-}; do ONLY+=("-only-testing:TeleplyUITests/ScreenshotTour/$test"); done
[ ${#ONLY[@]} -eq 0 ] && ONLY=("-only-testing:TeleplyUITests/ScreenshotTour")

cd "$IOS_DIR"
mkdir -p build
generate_project
# The widget extension cannot read the app's Assets.xcassets, so its copies of the marks and colours must stay
# identical to the app's (handoff 5.4); editing one side only fails here instead of drifting silently.
compare_island_assets() {
  local app="$IOS_DIR/Teleply/Resources/Assets.xcassets" ext="$IOS_DIR/TeleplyIslandWidget/Assets.xcassets" name
  for name in ClaudeMark.imageset CodexMark.imageset DeepSeekMark.imageset TeleplyMark.imageset ClaudeTint.colorset CodexTint.colorset \
              DeepSeekTint.colorset AskGo.colorset Success.colorset Danger.colorset Muted.colorset Ink.colorset \
              CardBackground.colorset CardForeground.colorset; do
    diff -r "$app/$name" "$ext/$name" >/dev/null || { echo "island asset copy differs from the app's: $name" >&2; exit 1; }
  done
}
compare_island_assets
swift test --package-path TeleplyCore

# The build machine is an M2, so the simulator builds are arm64 only; both architectures doubled the compile.
if [ "$MODE" = compile ]; then
  xcodebuild build -project Teleply.xcodeproj -scheme Teleply -configuration Debug \
    -destination 'generic/platform=iOS Simulator' -derivedDataPath build/dd \
    COMPILER_INDEX_STORE_ENABLE=NO CODE_SIGNING_ALLOWED=NO ARCHS=arm64 | xcbeautify
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

# The UDID of an available iPhone simulator on runtime $1, in this order: $DEVICE as the machine has it, or made
# new when the runtime supports it; another 6.9-inch phone (a Pro Max, newest first), had or made; else, as before,
# an ordinary phone with a warning that the pictures are not the App Store size. Build #4 showed that a fixed
# "iPhone 17" is refused on iOS 27.1 ("Incompatible device").
pick_device() {
  python3 - "$1" "$DEVICE" <<'PY'
import json, re, subprocess, sys
key, preferred = sys.argv[1], sys.argv[2]
runtime_id = "com.apple.CoreSimulator.SimRuntime." + key
def simctl(*args):
    return json.loads(subprocess.check_output(["xcrun", "simctl", "list", *args, "-j"]))
# An ordinary phone first, newest number first ("iPhone 18" before "iPhone 17"); a foldable such as
# "iPhone Duo" last, since its side column narrows the safe area (build 6adec604).
def rank(name):
    plain = re.fullmatch(r"iPhone (\d+)", name)
    if plain: return (0, -int(plain.group(1)))
    return (2, 0) if re.search(r"Duo|Fold", name) else (1, 0)
# A 6.9-inch phone, whose screenshots App Store Connect takes: a Pro Max, newest number first.
def pro_max(name):
    found = re.fullmatch(r"iPhone (\d+) Pro Max", name)
    return -int(found.group(1)) if found else None
phones = sorted((d for d in simctl("devices", "available")["devices"].get(runtime_id, []) if d["name"].startswith("iPhone")), key=lambda d: rank(d["name"]))
sys.stderr.write("iPhone simulators on %s: %s\n" % (key, ", ".join(d["name"] for d in phones)))
runtimes = simctl("runtimes")["runtimes"]
types = next((r.get("supportedDeviceTypes", []) for r in runtimes if r["identifier"] == runtime_id), [])
kinds = sorted((t for t in types if t["name"].startswith("iPhone")), key=lambda t: rank(t["name"]))
sys.stderr.write("iPhone types %s supports: %s\n" % (key, ", ".join(t["name"] for t in kinds)))
def use(device, why):
    sys.stderr.write("Using simulator %s (%s) on %s: %s\n" % (device["name"], device["udid"], key, why))
    print(device["udid"])
    sys.exit(0)
def make(kind, why):
    sys.stderr.write("Creating simulator %s on %s: %s\n" % (kind["name"], key, why))
    print(subprocess.check_output(["xcrun", "simctl", "create", "shots-" + key, kind["identifier"], runtime_id]).decode().strip())
    sys.exit(0)
# 1. The preferred phone, had or made.
for device in phones:
    if device["name"] == preferred: use(device, "the preferred phone")
for kind in kinds:
    if kind["name"] == preferred: make(kind, "the preferred phone")
# 2. Another 6.9-inch phone, had or made.
bigger = sorted((d for d in phones if pro_max(d["name"]) is not None), key=lambda d: pro_max(d["name"]))
if bigger: use(bigger[0], preferred + " is missing; another 6.9-inch phone")
bigger_kinds = sorted((t for t in kinds if pro_max(t["name"]) is not None), key=lambda t: pro_max(t["name"]))
if bigger_kinds: make(bigger_kinds[0], preferred + " is missing; another 6.9-inch phone")
# 3. An ordinary phone, as before. An existing plain phone is used as it is. When the machine only has a foldable
# for this runtime (build 6aded501: just "iPhone Duo" on 27.1, which moves the navigation bar into a side column),
# a plain one is made below if the runtime supports any.
sys.stderr.write("WARNING: no 6.9-inch iPhone on %s; these screenshots are not the size App Store Connect asks for\n" % key)
plain_kind = next((t for t in kinds if rank(t["name"])[0] < 2), None)
if phones and (rank(phones[0]["name"])[0] < 2 or plain_kind is None):
    use(phones[0], "fallback")
if not kinds:
    sys.stderr.write("No iPhone simulator for %s. Runtimes here: %s\n" % (runtime_id, ", ".join(r["identifier"] for r in runtimes)))
    sys.exit(1)
make(kinds[0], "fallback")
PY
}

xcodebuild build-for-testing -project Teleply.xcodeproj -scheme Teleply -configuration Debug \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build/dd \
  COMPILER_INDEX_STORE_ENABLE=NO ARCHS=arm64 | xcbeautify
XCTESTRUN=$(ls build/dd/Build/Products/*.xctestrun | head -n 1)

rm -rf build/shots && mkdir -p build/shots
for runtime in $RUNTIMES; do
  udid=$(pick_device "$runtime")
  xcrun simctl boot "$udid" 2>/dev/null || true  # already booted is fine
  xcrun simctl bootstatus "$udid" -b
  xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 || true
  TEST_RUNNER_SHOTS_DIR="$IOS_DIR/build/shots" xcodebuild test-without-building \
    -xctestrun "$XCTESTRUN" -destination "id=$udid" \
    "${ONLY[@]}" -collect-test-diagnostics never \
    -resultBundlePath "build/shots-$runtime.xcresult" | xcbeautify
  xcrun simctl shutdown "$udid" || true
done
ls -1 build/shots
