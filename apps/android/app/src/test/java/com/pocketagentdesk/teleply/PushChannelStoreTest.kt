package com.pocketagentdesk.teleply

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The key and the stream's place really stay in app-private storage (design-2 §1.1, §3.3), not only in a parsed string. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = android.app.Application::class)
class PushChannelStoreTest {
    private fun channel(context: Context) = PushChannel(context, { error("no network in this test") }, "1.0.10")

    @Test fun theKeyIsMadeOnceAndOnlyItsFingerprintLeaves() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val first = channel(context)
        val secret = first.secret()
        assertTrue(isPushSecret(secret))
        assertEquals(secret, channel(context).secret())
        assertEquals(sha256Hex(secret), first.token())
        assertEquals(pushToken(secret), first.token())
        assertEquals(first.label(), channel(context).label())
        assertEquals(first.language(), channel(context).language())
    }

    @Test fun thePlaceNeverGoesBackwardsAndANewRelayBootReplacesIt() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val channel = channel(context)
        assertNull(channel.since())
        channel.saveSince(PushSince("1a2b3c4d", 5))
        assertEquals(PushSince("1a2b3c4d", 5), channel(context).since())
        channel.advanceSince(PushSince("1a2b3c4d", 4))
        assertEquals(5L, channel.since()!!.seq)
        channel.advanceSince(PushSince("1a2b3c4d", 6))
        assertEquals(6L, channel.since()!!.seq)
        // The relay restarted: its seq starts again, and this boot is the one to resume.
        channel.advanceSince(PushSince("9f8e7d6c", 1))
        assertEquals(PushSince("9f8e7d6c", 1), channel.since())
        channel.clearSince()
        assertNull(channel.since())
    }

    @Test fun theSwitchAndTheServiceAddressAreSavedAndDroppedTogether() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val secret = newPushSecret()
        context.getSharedPreferences("native_push", Context.MODE_PRIVATE).edit()
            .putBoolean("enabled", true).putString("secret", secret)
            .putString("origin", "https://fixture.example.invalid").putString("since", "1a2b3c4d:9").commit()
        assertTrue(pushEnabledIn(context))
        assertEquals("https://fixture.example.invalid", pushOriginIn(context))
        val channel = channel(context)
        assertTrue(channel.enabled.value)
        channel.disable()
        assertFalse(channel.enabled.value)
        assertFalse(pushEnabledIn(context))
        assertNull(channel.since())
        // The key stays (the same phone to the relay) and so does the address it registered with.
        assertEquals(secret, channel(context).secret())
        assertEquals("https://fixture.example.invalid", pushOriginIn(context))
    }
}
