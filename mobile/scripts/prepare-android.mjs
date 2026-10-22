import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';

// Keep generated native projects disposable, as in the iOS build.
async function replace(path, from, to) {
  const text = await readFile(path, 'utf8');
  if (text.includes(to)) return;
  if (!text.includes(from)) throw new Error(`Unexpected Android template: ${path}`);
  await writeFile(path, text.replace(from, to));
}
await replace('android/variables.gradle', 'minSdkVersion = 24', 'minSdkVersion = 26');
await replace('android/app/build.gradle', 'android {', 'android {\n    buildToolsVersion "36.0.0"');
await replace('android/app/build.gradle', 'dependencies {', 'dependencies {\n    testImplementation "org.robolectric:robolectric:4.17"');
await replace('android/app/build.gradle', 'buildToolsVersion "36.0.0"', 'buildToolsVersion "36.0.0"\n    testOptions { unitTests.includeAndroidResources = true }');
const appGradle = await readFile('android/app/build.gradle', 'utf8');
await writeFile('android/app/build.gradle', appGradle.replace(/versionCode \d+/, 'versionCode 3').replace(/versionName "[^"]+"/, 'versionName "0.3.0"'));
await copyFile('dist/account-theme.js', 'android/app/src/main/assets/account-theme.js');
await replace('android/app/src/main/AndroidManifest.xml', 'android:allowBackup="true"',
  'android:allowBackup="false"\n        android:usesCleartextTraffic="false"');
await replace('android/app/src/main/AndroidManifest.xml',
  '<manifest xmlns:android="http://schemas.android.com/apk/res/android">',
  '<manifest xmlns:android="http://schemas.android.com/apk/res/android" xmlns:tools="http://schemas.android.com/tools">');
await replace('android/app/src/main/AndroidManifest.xml', '<!-- Permissions -->',
  `<!-- Permissions -->
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" tools:node="remove" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" tools:node="remove" />`);
await replace('android/app/src/main/AndroidManifest.xml', '    </application>',
  `        <activity android:name=".RemoteBrowserActivity" android:exported="false"
            android:configChanges="orientation|keyboardHidden|keyboard|screenSize|screenLayout|uiMode|smallestScreenSize|density"
            android:theme="@style/AppTheme.NoActionBar" />
    </application>`);
const source = 'android/app/src/main/java/com/pocketagentdesk/remote';
await mkdir(source, { recursive: true });
for (const name of ['RemoteBrowserPlugin', 'BrowserPolicy', 'RemoteBrowserActivity'])
  await copyFile(`native/android/${name}.java`, `${source}/${name}.java`);
const tests = 'android/app/src/test/java/com/pocketagentdesk/remote';
await mkdir(tests, { recursive: true });
await copyFile('tests/android/BrowserPolicyTest.java', `${tests}/BrowserPolicyTest.java`);
await copyFile('tests/android/FirstLoginTest.java', `${tests}/FirstLoginTest.java`);
await writeFile(`${source}/MainActivity.java`, `package com.pocketagentdesk.remote;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
public class MainActivity extends BridgeActivity {
    @Override public void onCreate(Bundle state) {
        registerPlugin(RemoteBrowserPlugin.class);
        super.onCreate(state);
    }
}
`);
// Use the smaller distribution without sources; Gradle itself remains pinned.
await replace('android/gradle/wrapper/gradle-wrapper.properties',
  'gradle-8.14.3-all.zip', 'gradle-8.14.3-bin.zip');
