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

xcodebuild build-for-testing -project Teleply.xcodeproj -scheme Teleply -configuration Debug \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build/dd \
  COMPILER_INDEX_STORE_ENABLE=NO | xcbeautify
XCTESTRUN=$(ls build/dd/Build/Products/*.xctestrun | head -n 1)

rm -rf build/shots && mkdir -p build/shots
for runtime in $RUNTIMES; do
  udid=$(xcrun simctl create "shots-$runtime" "$DEVICE" "com.apple.CoreSimulator.SimRuntime.$runtime" || true)
  if [ -z "$udid" ]; then
    echo "Could not create \"$DEVICE\" on $runtime. Device types on this machine:"
    xcrun simctl list devicetypes | grep -i iphone || true
    exit 1
  fi
  xcrun simctl boot "$udid"
  xcrun simctl bootstatus "$udid" -b
  xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 || true
  TEST_RUNNER_SHOTS_DIR="$IOS_DIR/build/shots" xcodebuild test-without-building \
    -xctestrun "$XCTESTRUN" -destination "id=$udid" \
    -only-testing:TeleplyUITests/ScreenshotTour \
    -resultBundlePath "build/shots-$runtime.xcresult" | xcbeautify
  xcrun simctl shutdown "$udid" || true
done
ls -1 build/shots
