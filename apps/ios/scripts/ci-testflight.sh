#!/bin/bash
# ios-native-testflight: an App Store signed archive with the next TestFlight build number, checked for what
# App Store Connect most often turns away. codemagic.yaml then uploads it; internal testing only, nothing is
# submitted for review.
set -euo pipefail
source "$(dirname "$0")/ci-common.sh"

BUNDLE_ID=com.pocketagentdesk.teleply
APPLE_APP_ID=6826968427  # App Store Connect → 遥应 → App 信息 → Apple ID

# The integration in codemagic.yaml gives app-store-connect its credentials. No build yet reads as 0.
latest_build_number() {
  app-store-connect get-latest-testflight-build-number "$APPLE_APP_ID" 2>/dev/null | tail -n 1 || echo 0
}

fail() { echo "IPA check failed: $1" >&2; exit 1; }

check_ipa() {
  local ipa="$1" build="$2" unpacked app plist
  unpacked=$(mktemp -d)
  unzip -q "$ipa" -d "$unpacked"
  app="$unpacked/Payload/Teleply.app"
  plist="$app/Info.plist"
  plutil -p "$plist"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$plist")" = "$BUNDLE_ID" ] || fail "bundle ID"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$plist")" = "$build" ] || fail "build number"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :ITSAppUsesNonExemptEncryption' "$plist")" = "false" ] || fail "encryption declaration"
  # iOS keeps the icon name inside CFBundleIcons (App Store Connect's ITMS-90713 checks it there).
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIcons:CFBundlePrimaryIcon:CFBundleIconName' "$plist")" = "AppIcon" ] || fail "app icon (CFBundleIcons)"
  # iPhone only: once an App Store build supports iPad, later builds cannot drop it.
  { [ "$(/usr/libexec/PlistBuddy -c 'Print :UIDeviceFamily:0' "$plist")" = "1" ] &&
    ! /usr/libexec/PlistBuddy -c 'Print :UIDeviceFamily:1' "$plist" >/dev/null 2>&1; } || fail "iPhone only (UIDeviceFamily)"
  [ -f "$app/PrivacyInfo.xcprivacy" ] || fail "privacy manifest"
  [ -d "$app/zh-Hans.lproj" ] || fail "Simplified Chinese localization"
  echo "IPA checks passed for build $build"
}

cd "$IOS_DIR"
LATEST=$(latest_build_number)
case "$LATEST" in ''|*[!0-9]*) LATEST=0 ;; esac
BUILD=$((LATEST + 1))
echo "Next TestFlight build number: $BUILD"
sed -i '' -E "s/^( *CURRENT_PROJECT_VERSION: ).*/\1\"$BUILD\"/" project.yml

generate_project
swift test --package-path TeleplyCore
xcode-project use-profiles --project Teleply.xcodeproj
xcode-project build-ipa --project Teleply.xcodeproj --scheme Teleply --config Release
# A delegate method that only "nearly matches" is never called (RedirectRefusal would let redirects through).
if grep -h "nearly matches optional requirement" /tmp/xcodebuild_logs/*.log 2>/dev/null; then
  fail "a delegate method does not match its protocol (warning above)"
fi
check_ipa "$(ls build/ios/ipa/*.ipa | head -n 1)" "$BUILD"
