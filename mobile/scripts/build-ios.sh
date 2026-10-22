#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
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
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Debug \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build
ditto -c -k --sequesterRsrc --keepParent \
  build/DerivedData/Build/Products/Debug-iphonesimulator/App.app build/AgentRemote-simulator.zip
# Keep the resolved Swift graph as evidence for the first cloud run.
find ios -name Package.resolved -exec cp {} build/Package.resolved \;
