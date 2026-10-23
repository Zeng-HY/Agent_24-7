import { readFile, writeFile, copyFile } from 'node:fs/promises';
// cap sync regenerates this manifest: pin the native runtime after every sync.
const manifest = 'ios/App/CapApp-SPM/Package.swift';
let swift = await readFile(manifest, 'utf8');
const runtime = /url: "https:\/\/github.com\/ionic-team\/capacitor-swift-pm.git", (?:from|exact): "[^"]+"/;
if (!runtime.test(swift)) throw Error('Unexpected Capacitor SPM manifest; review before building.');
swift = swift.replace(runtime, 'url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.5.3"');
await writeFile(manifest, swift);
const plist = 'ios/App/App/Info.plist';
let xml = await readFile(plist, 'utf8');
const descriptions = {
  NSCameraUsageDescription: '选择拍照时，用于向自己的电脑发送图片。',
  NSMicrophoneUsageDescription: '启用语音输入时，用于录制要发送到自己电脑的语音。',
  NSPhotoLibraryUsageDescription: '选择图片时，用于发送到自己的电脑。'
};
for (const [key, value] of Object.entries(descriptions)) {
  if (!xml.includes('<key>' + key + '</key>')) xml = xml.replace('</dict>\n</plist>', `<key>${key}</key><string>${value}</string>\n</dict>\n</plist>`);
  if (!xml.includes('<key>' + key + '</key>')) throw Error('Unexpected Info.plist format');
}
if (/NSAllowsArbitraryLoads/.test(xml)) throw Error('Unexpected ATS exception');
await writeFile(plist, xml);
// The home-screen icon is the Agent Remote mark (written by brand/make_icons.py), not Capacitor's; launching shows plain white.
const assets = 'ios/App/App/Assets.xcassets';
for (const [set, source, names] of [['AppIcon.appiconset', 'resources/ios/AppIcon-512@2x.png', ['AppIcon-512@2x.png']],
  ['Splash.imageset', 'resources/ios/splash.png', ['splash-2732x2732.png', 'splash-2732x2732-1.png', 'splash-2732x2732-2.png']]]) {
  const contents = await readFile(`${assets}/${set}/Contents.json`, 'utf8');
  for (const name of names) {
    if (!contents.includes(`"${name}"`)) throw Error(`Unexpected ${set}; review before building.`);
    await copyFile(source, `${assets}/${set}/${name}`);
  }
}
console.log('Native runtime pinned; media usage descriptions, app icon and plain launch screen applied; ATS unchanged.');
