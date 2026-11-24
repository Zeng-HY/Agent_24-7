package com.pocketagentdesk.teleply

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 遥应通知's key, fingerprint and saved place (design-2 §1.1), away from Android. */
class PushChannelTest {
    @Test fun secretIsThirtyTwoRandomBytesAsSixtyFourLowerHexDigits() {
        val secrets = (1..8).map { newPushSecret() }
        secrets.forEach { secret ->
            assertEquals(64, secret.length)
            assertTrue(isPushSecret(secret))
            assertTrue(secret.all { it in "0123456789abcdef" })
        }
        assertEquals("eight draws differ", 8, secrets.toSet().size)
    }

    @Test fun tokenIsSha256OfTheKeyAndNeverTheKeyItself() {
        // Vectors from a plain SHA-256 of the UTF-8 words, as the relay computes it.
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", pushToken(""))
        assertEquals("60e05bd1b195af2f94112fa7197a5c88289058840ce7c6df9693756bc6250f55", pushToken("00".repeat(32)))
        assertEquals("b3c53c08828847f11b3083a5b1fa83ddf6751112653f0fd9d563754092ec65f7", pushToken("fixture-secret"))
        val secret = newPushSecret()
        val token = pushToken(secret)
        assertEquals(64, token.length)
        assertTrue(isPushSecret(token))
        assertNotEquals(secret, token)
    }

    @Test fun sinceSavesAndReadsTheRelayBootAndPlace() {
        val value = PushSince("1a2b3c4d", 42)
        assertEquals("1a2b3c4d:42", value.format())
        assertEquals(value, PushSince.parse("1a2b3c4d:42"))
        assertEquals(value, PushSince.parse("  1a2b3c4d:42  "))
        assertEquals(PushSince("a", 0), PushSince.parse("a:0"))
        assertNull(PushSince.parse(null))
        assertNull(PushSince.parse(""))
        assertNull(PushSince.parse("   "))
        assertNull(PushSince.parse("1a2b3c4d"))
        assertNull(PushSince.parse(":9"))
        assertNull(PushSince.parse("1a2b3c4d:"))
        assertNull(PushSince.parse("1a2b3c4d:-1"))
        assertNull(PushSince.parse("1a2b3c4d:not-a-number"))
        // An empty boot means "nothing to resume from", which is sent as no `since` at all.
        assertEquals("", PushSince("", 9).format())
    }

    @Test fun labelAndLanguageAreWhatTheRelayTakes() {
        assertEquals("Xiaomi 15", pushLabel(" Xiaomi ", " 15 "))
        assertEquals("Pixel", pushLabel("", "Pixel"))
        assertEquals(40, pushLabel("a".repeat(50), "b").length)
        assertEquals("zh-Hans", pushLanguage("zh-Hans"))
        assertEquals("zh-Hans", pushLanguage("zh-TW"))
        assertEquals("zh-Hans", pushLanguage("ZH"))
        assertEquals("en", pushLanguage("en-US"))
        assertEquals("en", pushLanguage("de"))
    }

    @Test fun statusLineSaysWhatThePhoneIsDoing() {
        assertEquals("未开启", pushStatusText(PushStatus()))
        assertEquals("在接收 · 2 台电脑在线", pushStatusText(PushStatus(true, PushPhase.Receiving, online = 2, computers = 2)))
        assertEquals("在接收 · 没有电脑在线", pushStatusText(PushStatus(true, PushPhase.Receiving, online = 0, computers = 2)))
        assertEquals("连不上中转，正在重试", pushStatusText(PushStatus(true, PushPhase.Retrying, online = 1)))
        assertEquals("连不上中转，正在重试", pushStatusText(PushStatus(true, PushPhase.Connecting)))
        assertEquals("需要重新打开", pushStatusText(PushStatus(true, PushPhase.NeedsRenew)))
        assertEquals("钥匙不对", pushStatusText(PushStatus(true, PushPhase.Error, reason = "钥匙不对")))
        assertEquals("连接出错", pushStatusText(PushStatus(true, PushPhase.Error)))
        assertEquals("后台没起来：打开遥应一次就好", pushStatusText(PushStatus(true, PushPhase.Error, reason = PushForegroundFailedText)))
    }

    @Test fun aSignInThatRanOutIsSaidInThePagesWords() {
        assertEquals("登录已失效，请重新登录后再打开遥应通知", pushFailureText(ServiceFailure(401)))
        assertEquals("这个服务还没有安卓通知，请稍后再试", pushFailureText(ServiceFailure(404)))
        assertEquals("连不上中转，请检查网络后重试", pushFailureText(java.io.IOException()))
        assertEquals("电脑没有回应", pushFailureText(java.io.IOException("电脑没有回应")))
    }

    @Test fun theBackgroundLineNamesTheMakerAndFallsBackToTheGeneralOne() {
        assertTrue(backgroundHint("Xiaomi").contains("省电策略"))
        assertTrue(backgroundHint("Redmi").contains("省电策略"))
        assertTrue(backgroundHint("HUAWEI").contains("耗电详情"))
        assertTrue(backgroundHint("HONOR").contains("耗电详情"))
        assertTrue(backgroundHint("OPPO").contains("应用耗电管理"))
        assertTrue(backgroundHint("OnePlus").contains("应用耗电管理"))
        assertTrue(backgroundHint("realme").contains("应用耗电管理"))
        assertTrue(backgroundHint("vivo").contains("后台耗电管理"))
        assertTrue(backgroundHint("iQOO").contains("后台耗电管理"))
        assertTrue(backgroundHint("samsung").contains("从不休眠"))
        assertTrue(backgroundHint("Sony").contains("省电限制"))
        assertTrue(backgroundHint("").contains("省电限制"))
    }
}
