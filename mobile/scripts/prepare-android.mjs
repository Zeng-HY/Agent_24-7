import { readFile, writeFile, mkdir, copyFile, cp } from 'node:fs/promises';

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
const version = JSON.parse(await readFile('android-version.json', 'utf8'));
if (!/^\d+\.\d+\.\d+$/.test(version.name) || !Number.isSafeInteger(version.code) || version.code < 1) throw new Error('Invalid Android version');
await writeFile('android/app/build.gradle', appGradle.replace(/versionCode \d+/, `versionCode ${version.code}`).replace(/versionName "[^"]+"/, `versionName "${version.name}"`));
await replace('android/app/src/main/AndroidManifest.xml', 'android:allowBackup="true"',
  'android:allowBackup="false"\n        android:usesCleartextTraffic="false"');
await replace('android/app/src/main/AndroidManifest.xml',
  '<manifest xmlns:android="http://schemas.android.com/apk/res/android">',
  '<manifest xmlns:android="http://schemas.android.com/apk/res/android" xmlns:tools="http://schemas.android.com/tools">');
await replace('android/app/src/main/AndroidManifest.xml', '    </application>',
  `        <activity android:name=".RemoteBrowserActivity" android:exported="false"
            android:configChanges="orientation|keyboardHidden|keyboard|screenSize|screenLayout|uiMode|smallestScreenSize|density"
            android:theme="@style/AppTheme.NoActionBar" />
    </application>`);
const manifestPath='android/app/src/main/AndroidManifest.xml';
let manifest=await readFile(manifestPath,'utf8');
// These owned permissions may already exist from an earlier prepare/sync run.
manifest=manifest.replace(/\s*<uses-permission android:name="android.permission.(?:REQUEST_INSTALL_PACKAGES|ACCESS_COARSE_LOCATION|ACCESS_FINE_LOCATION)"[^>]*\/>/g,'');
manifest=manifest.replace('</manifest>', `    <uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" tools:node="remove" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" tools:node="remove" />
</manifest>`);
await writeFile(manifestPath,manifest);
const source = 'android/app/src/main/java/com/pocketagentdesk/remote';
await mkdir(source, { recursive: true });
for (const name of ['RemoteBrowserPlugin', 'BrowserPolicy', 'RemoteBrowserActivity', 'AppUpdater', 'UpdatePolicy', 'ThemePolicy'])
  await copyFile(`native/android/${name}.java`, `${source}/${name}.java`);
const tests = 'android/app/src/test/java/com/pocketagentdesk/remote';
await mkdir(tests, { recursive: true });
await copyFile('tests/android/BrowserPolicyTest.java', `${tests}/BrowserPolicyTest.java`);
await copyFile('tests/android/FirstLoginTest.java', `${tests}/FirstLoginTest.java`);
await copyFile('tests/android/UpdatePolicyTest.java', `${tests}/UpdatePolicyTest.java`);
await writeFile(`${source}/MainActivity.java`, `package com.pocketagentdesk.remote;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
public class MainActivity extends BridgeActivity {
    @Override public void onCreate(Bundle state) {
        registerPlugin(RemoteBrowserPlugin.class);
        super.onCreate(state);
        ThemePolicy.apply(this,getBridge().getWebView());
    }
}
`);
// The launcher icon is the Agent Remote mark (written by brand/make_icons.py), not Capacitor's; launching shows plain white.
const res = 'android/app/src/main/res';
await cp('resources/android', res, {recursive:true});
const stylesPath=`${res}/values/styles.xml`;
await writeFile(stylesPath,(await readFile(stylesPath,'utf8')).replace(/<item name="android:background">(?:@drawable\/splash|@android:color\/white)<\/item>/g,'<item name="android:background">@color/teleply_window_background</item>'));
// Use the smaller distribution without sources; Gradle itself remains pinned.
await replace('android/gradle/wrapper/gradle-wrapper.properties',
  'gradle-8.14.3-all.zip', 'gradle-8.14.3-bin.zip');

// The application id stays stable so existing installations can update in place.
const stringsPath = `${res}/values/strings.xml`;
const strings = await readFile(stringsPath, "utf8");
await writeFile(stringsPath, strings.replace(/(<string name="(?:app_name|title_activity_main)">)[^<]*(<\/string>)/g, "$1遥应$2"));
