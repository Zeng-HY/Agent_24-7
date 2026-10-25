# Release build (0.8): R8 shrinks and optimises; the libraries bring their own rules (Room, OkHttp, coroutines, Compose).
# Nothing in the app is reached by reflection: JSON is read with org.json by name, never mapped onto classes.

# OkHttp's optional TLS providers are not on Android.
-dontwarn org.bouncycastle.jsse.**
-dontwarn org.conscrypt.**
-dontwarn org.openjsse.**
