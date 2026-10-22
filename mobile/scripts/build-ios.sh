#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
target="${1:-simulator}"
case "$target" in simulator|device) ;; *) echo 'Expected simulator or device' >&2; exit 2 ;; esac
if [ "$(uname -s)" != Darwin ]; then
  echo 'Xcode compilation requires macOS.' >&2
  exit 1
fi
npm ci --no-fund
npm test
npm run check:ci
npm run build
if [ ! -d ios ]; then npm run ios:add; fi
npm run ios:sync
node scripts/prepare-ios.mjs
mkdir -p build
xcodebuild -resolvePackageDependencies -project ios/App/App.xcodeproj -scheme App
if [ "$target" = simulator ]; then
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Debug \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build
ditto -c -k --sequesterRsrc --keepParent \
  build/DerivedData/Build/Products/Debug-iphonesimulator/App.app build/AgentRemote-simulator.zip
else
  xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
    -sdk iphoneos -destination 'generic/platform=iOS' \
    -derivedDataPath build/DeviceDerivedData CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build
  app=build/DeviceDerivedData/Build/Products/Release-iphoneos/App.app
  test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleSupportedPlatforms:0' "$app/Info.plist")" = iPhoneOS
  xcrun lipo "$app/App" -verify_arch arm64
  mkdir -p build/sideload/Payload
  ditto "$app" build/sideload/Payload/App.app
  (cd build/sideload && ditto -c -k --keepParent Payload ../AgentRemote-unsigned.ipa)
fi
# Keep the resolved Swift graph as evidence for the first cloud run.
find ios -name Package.resolved -exec cp {} build/Package.resolved \;
