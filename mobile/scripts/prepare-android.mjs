import { readFile, writeFile } from 'node:fs/promises';

// Keep generated native projects disposable, as in the iOS build.
async function replace(path, from, to) {
  const text = await readFile(path, 'utf8');
  if (text.includes(to)) return;
  if (!text.includes(from)) throw new Error(`Unexpected Android template: ${path}`);
  await writeFile(path, text.replace(from, to));
}
await replace('android/variables.gradle', 'minSdkVersion = 24', 'minSdkVersion = 26');
await replace('android/app/build.gradle', 'android {', 'android {\n    buildToolsVersion "36.0.0"');
await replace('android/app/src/main/AndroidManifest.xml', 'android:allowBackup="true"',
  'android:allowBackup="false"\n        android:usesCleartextTraffic="false"');
await replace('android/app/src/main/AndroidManifest.xml',
  '<manifest xmlns:android="http://schemas.android.com/apk/res/android">',
  '<manifest xmlns:android="http://schemas.android.com/apk/res/android" xmlns:tools="http://schemas.android.com/tools">');
await replace('android/app/src/main/AndroidManifest.xml', '<!-- Permissions -->',
  `<!-- Permissions -->
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" tools:node="remove" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" tools:node="remove" />`);
// Use the smaller distribution without sources; Gradle itself remains pinned.
await replace('android/gradle/wrapper/gradle-wrapper.properties',
  'gradle-8.14.3-all.zip', 'gradle-8.14.3-bin.zip');
