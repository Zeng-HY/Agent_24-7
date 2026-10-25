plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.kapt")
}
android {
    namespace = "com.pocketagentdesk.nativepreview"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.pocketagentdesk.remote.nativepreview"
        minSdk = 26
        targetSdk = 36
        versionCode = 9
        versionName = "0.9.0-nativepreview"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
        manifestPlaceholders["appLabel"] = "遥应 原生预览"
    }
    // One key for every Teleply Android package (0.8, user decision): this computer's Android debug key, the one the
    // old app (mobile/, PocketAgentDesk 0.5.0-0.7.4) is signed with. An update installs only over the same key, so
    // builds come from this computer; the key is never copied into the project. 0.7 and earlier used .local/nativepreview.jks.
    val sharedKey = file((System.getenv("ANDROID_USER_HOME") ?: (System.getProperty("user.home") + "/.android")) + "/debug.keystore")
    signingConfigs {
        getByName("debug") { storeFile = sharedKey }
        create("teleply") {
            storeFile = sharedKey
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }
    buildTypes {
        // The development copy installs beside the app (its own id and name), so trying it never touches the app's login.
        debug { isDebuggable = true;applicationIdSuffix = ".dev";versionNameSuffix = "-dev";manifestPlaceholders["appLabel"] = "遥应 开发版";signingConfig = signingConfigs.getByName("teleply") }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("teleply")
        }
        // The release build as the development copy: measures and checks what users get, beside the app.
        create("benchmark") { initWith(getByName("release"));isDebuggable=false;applicationIdSuffix=".dev";versionNameSuffix="-perf";manifestPlaceholders["appLabel"] = "遥应 开发版";matchingFallbacks += listOf("release") }
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
