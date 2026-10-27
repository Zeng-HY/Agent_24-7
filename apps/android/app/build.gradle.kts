import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.kapt")
}
// Signing (1.0, user decision 2026-10-25): the app has its own release key, kept outside the project with its password
// in ~/.android/teleply-signing (or TELEPLY_SIGNING_DIR). Every later update must carry it, so that folder is backed up.
// The development and measuring copies keep this computer's Android debug key, which signed 0.8-0.9 and the old app.
val debugKey = file((System.getenv("ANDROID_USER_HOME") ?: (System.getProperty("user.home") + "/.android")) + "/debug.keystore")
val releaseDir = file(System.getenv("TELEPLY_SIGNING_DIR") ?: (System.getProperty("user.home") + "/.android/teleply-signing"))
val releaseKey = File(releaseDir, "release.properties").takeIf { it.isFile }?.let { f -> Properties().apply { f.inputStream().use { load(it) } } }
android {
    namespace = "com.pocketagentdesk.teleply"
    compileSdk = 36
    defaultConfig {
        // 1.0: the official app, named just 遥应. A new id is a new app to a phone, so the preview (….remote.nativepreview,
        // 0.9 and earlier) and the archived shell (….remote, mobile/) stay installed beside it until removed by hand.
        applicationId = "com.pocketagentdesk.teleply"
        minSdk = 26
        targetSdk = 36
        versionCode = 15
        versionName = "1.0.4"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
        manifestPlaceholders["appLabel"] = "遥应"
    }
    signingConfigs {
        getByName("debug") { storeFile = debugKey }
        if (releaseKey != null) create("teleply") {
            storeFile = File(releaseDir, releaseKey.getProperty("storeFile"))
            storePassword = releaseKey.getProperty("password")
            keyAlias = releaseKey.getProperty("alias")
            keyPassword = releaseKey.getProperty("password")
        }
    }
    buildTypes {
        // The development copy installs beside the app (its own id and name), so trying it never touches the app's login.
        debug { isDebuggable = true;applicationIdSuffix = ".dev";versionNameSuffix = "-dev";manifestPlaceholders["appLabel"] = "遥应 开发版";signingConfig = signingConfigs.getByName("debug") }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("teleply")
        }
        // The release build, profileable (src/benchmark), as its own copy (0.9.1): measures what users get beside the app.
        // Not the .dev copy any more: that one may be signed in to a real account, and a measured copy must never be.
        create("benchmark") { initWith(getByName("release"));isDebuggable=false;applicationIdSuffix=".perf";versionNameSuffix="-perf";manifestPlaceholders["appLabel"] = "遥应 性能版";matchingFallbacks += listOf("release");signingConfig = signingConfigs.getByName("debug") }
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    testOptions { unitTests.isIncludeAndroidResources = true
        unitTests.all { it.systemProperty("robolectric.dependency.repo.url", "https://repo.maven.apache.org/maven2") }
    }
    sourceSets.getByName("test").java.srcDir("src/sharedTest/java")
    sourceSets.getByName("androidTest").java.srcDir("src/sharedTest/java")
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}
// Without the app's key a release would be another app to every phone: stop instead of signing with anything else.
tasks.matching { it.name == "packageRelease" }.configureEach {
    doFirst { check(releaseKey != null) { "缺少遥应的正式签名：找不到 ${releaseDir}/release.properties（见 README「发布新版本」）" } }
}
dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation(platform("androidx.compose:compose-bom:2025.10.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3:1.4.0")
    implementation("androidx.compose.material:material-icons-core:1.7.8")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.datastore:datastore-preferences:1.1.7")
    implementation("androidx.room:room-runtime:2.8.2")
    implementation("androidx.room:room-ktx:2.8.2")
    kapt("androidx.room:room-compiler:2.8.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:okhttp-sse:4.12.0")
    implementation("org.commonmark:commonmark:0.24.0")
    implementation("org.commonmark:commonmark-ext-gfm-tables:0.24.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20250517")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("org.robolectric:robolectric:4.16")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    debugImplementation("androidx.compose.ui:ui-tooling")
    androidTestImplementation(platform("androidx.compose:compose-bom:2025.10.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
}

kapt { arguments { arg("room.schemaLocation", "$projectDir/schemas") } }
