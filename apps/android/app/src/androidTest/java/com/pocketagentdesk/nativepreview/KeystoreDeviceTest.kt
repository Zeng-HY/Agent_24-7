package com.pocketagentdesk.nativepreview
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
@RunWith(AndroidJUnit4::class)
class KeystoreDeviceTest {
    @Test fun credentialsAreEncryptedAndBoundToOrigin() {
        val context=ApplicationProvider.getApplicationContext<Context>()
        val origin="https://keystore-test.invalid/"
        val other="https://keystore-other-test.invalid/"
        val cookie="__Host-ar_account=synthetic-device-test; Path=/; Secure; HttpOnly"
        val vault=SecureCookieVault(context)
        try {
            vault.write(origin,cookie)
            assertEquals(cookie,SecureCookieVault(context).read(origin))
            assertNull(vault.read(other))
            val raw=context.getSharedPreferences("keystore_credentials",Context.MODE_PRIVATE).all.values.joinToString()
            assertFalse(raw.contains("synthetic-device-test"))
        } finally { vault.write(origin,null);vault.write(other,null) }
    }
}
