#!/bin/bash
# ios-native-testflight: an App Store signed archive with the next TestFlight build number, checked for what
# App Store Connect most often turns away. codemagic.yaml then uploads it; internal testing only, nothing is
# submitted for review.
set -euo pipefail
source "$(dirname "$0")/ci-common.sh"

BUNDLE_ID=com.pocketagentdesk.teleply
APPLE_APP_ID=6826968427  # App Store Connect → 遥应 → App 信息 → Apple ID

# The integration in codemagic.yaml gives app-store-connect its credentials.
# 11-16: a failed read used to count as "no build yet" (0), so the archive was numbered 1 and only the upload failed,
# with no word of why. Now it stops here and shows what App Store Connect said (a key without access to the app,
# an agreement waiting in App Store Connect…). The app has had builds since 10-26, so 0 is never right.
latest_build_number() {
  local out
  if ! out=$(app-store-connect get-latest-testflight-build-number "$APPLE_APP_ID" 2>&1); then
    echo "$out" | tail -n 20 >&2
    echo "Could not read the latest TestFlight build number of app $APPLE_APP_ID: see App Store Connect's answer above." >&2
    exit 1
  fi
  echo "$out" | tail -n 1
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
  # iPhone and iPad: once an App Store build supports iPad, later builds cannot drop it, so both must be in the
  # package (and the widget extension must say the same as the app).
  family() { /usr/libexec/PlistBuddy -c "Print :UIDeviceFamily:$2" "$1" 2>/dev/null || true; }
  [ "$(family "$plist" 0)" = "1" ] && [ "$(family "$plist" 1)" = "2" ] || fail "device family (iPhone and iPad)"
  [ -f "$app/PrivacyInfo.xcprivacy" ] || fail "privacy manifest"
  # 遥应通知: the App Store profile must carry push (App ID capability on, profile made again after it), in the
  # production environment TestFlight uses; a token from any other would not reach the phone.
  codesign -d --entitlements - --xml "$app" > "$unpacked/entitlements.plist" 2>/dev/null || fail "entitlements unreadable"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :aps-environment' "$unpacked/entitlements.plist" 2>/dev/null)" = "production" ] ||
    fail "push entitlement (aps-environment production): is the profile made again with Push Notifications on?"
  [ -d "$app/zh-Hans.lproj" ] || fail "Simplified Chinese localization"
  [ -d "$app/en.lproj" ] || fail "English localization (en.lproj)"
  # 灵动岛: the Live Activity widget extension must be embedded, use the island's App ID and profile, carry the same
  # version as the app (App Store Connect refuses a mismatch) and be a WidgetKit extension.
  ext="$app/PlugIns/TeleplyIslandWidget.appex"
  [ -d "$ext" ] || fail "island widget extension (TeleplyIslandWidget.appex)"
  extpl="$ext/Info.plist"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$extpl")" = "$BUNDLE_ID.island" ] || fail "widget bundle ID"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$extpl")" = "$build" ] || fail "widget build number"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$extpl")" = \
    "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist")" ] || fail "widget version"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :NSExtension:NSExtensionPointIdentifier' "$extpl")" = "com.apple.widgetkit-extension" ] ||
    fail "widget extension point"
  [ "$(family "$extpl" 0)" = "1" ] && [ "$(family "$extpl" 1)" = "2" ] || fail "widget device family (iPhone and iPad)"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :NSSupportsLiveActivities' "$plist")" = "true" ] || fail "NSSupportsLiveActivities"
  echo "IPA checks passed for build $build"
}

cd "$IOS_DIR"
LATEST=$(latest_build_number)
case "$LATEST" in ''|*[!0-9]*) echo "Unexpected latest TestFlight build number: '$LATEST'" >&2; exit 1 ;; esac
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
