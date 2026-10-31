package com.pocketagentdesk.teleply

import org.junit.Test
import org.junit.Assert.*

class PlatformPolicyTest {
    @Test fun lateSpeechCannotCrossSessionCancelOrIdentity() {
        val key=ChatKey("owner","device","chat")
        val gate=SpeechGate(key);val first=gate.start();assertTrue(gate.accepts(first,key))
        gate.cancel();assertFalse(gate.accepts(first,key));val second=gate.start()
        assertFalse(gate.accepts(second,key.copy(app="deepseek")))
        assertFalse(gate.accepts(second,key.copy(scope="other")))
        gate.close();assertFalse(gate.accepts(second,key))
    }
    @Test fun speechAppendsWithoutDeletingNewTyping() {
        assertEquals("已有新输入\n识别内容",appendDictation("已有新输入"," 识别内容 "))
        assertEquals("已有新输入",appendDictation("已有新输入"," "))
        assertEquals("测试",appendDictation("","测试"))
    }
    @Test fun notificationsDeduplicateAndNeverCallAnUnknownOutcomeCompleted() {
        val running=WatchSignal(true,"","turn","inProgress")
        val done=WatchSignal(false,"","turn","completed")
        assertNull(notificationChange(null,done));assertNotNull(notificationChange(running,done));assertNull(notificationChange(done,done))
        val unknown=done.copy(status="")
        assertFalse(notificationChange(running,unknown)!!.contains("已完成"))
        assertNotNull(notificationChange(done,done.copy(questions="q1")))
        assertNull(notificationChange(done.copy(questions="q1"),done.copy(questions="q1")))
    }
    @Test fun answeredHistoryDoesNotLookLikePendingQuestion() {
        val control=parseControl(org.json.JSONObject("""{"available":true,"questions":[{"id":"old","status":"answered"},{"id":"new","status":"pending"}]}"""))
        assertEquals("new",WatchSignal.from(control).questions)
    }
    @Test fun watchScopeRequiresSameOriginAndAccountScope() {
        val target=WatchTarget("https://example.invalid/",ChatKey("owner","d","c"),"random")
        val p=Preferences(origin=target.origin,scope="owner")
        assertTrue(watchBelongs(target,p));assertFalse(watchBelongs(target,p.copy(scope="other")));assertFalse(watchBelongs(target,p.copy(origin="https://another.invalid/")))
    }
    /** 10-31: nothing saved is the default service, however the check's address is written; anything else is not. */
    @Test fun watchOnTheDefaultServiceBelongsWhenNothingIsSaved() {
        val target=WatchTarget(DefaultOrigin,ChatKey("owner","d","c"),"random");val p=Preferences(origin="",scope="owner")
        assertTrue(watchBelongs(target,p));assertTrue(watchBelongs(target.copy(origin="https://app.pocketagentdesk.com/"),p))
        assertTrue(watchBelongs(target,p.copy(origin="https://APP.pocketagentdesk.com/")))
        assertFalse(watchBelongs(target.copy(origin=OldDefaultOrigin),p));assertFalse(watchBelongs(target.copy(origin="fixture://local"),p))
        assertFalse(watchBelongs(target,p.copy(origin="https://example.invalid/")));assertFalse(watchBelongs(target,p.copy(scope="")))
    }
    @Test fun responsiveLayoutLeavesRoomForTextAndKeyboard() {
        assertFalse(useTwoPane(412f,800f,1f));assertTrue(useTwoPane(1200f,800f,1f))
        assertFalse(useTwoPane(1200f,800f,2f));assertTrue(useTwoPane(1600f,900f,2f));assertFalse(useTwoPane(1000f,400f,1f))
    }
    @Test fun cacheBoundAndOriginalMarkdownArePreserved() {
        val cache=MarkdownCache(2,80);val a=cache.document("**first**");assertSame(a,cache.document("**first**"))
        cache.document("second");cache.document("third");assertEquals(2,cache.size())
        cache.document("x".repeat(100));assertEquals(2,cache.size())
        assertEquals("first",plain(a));cache.clear();assertEquals(0,cache.size())
    }
    @Test fun sharedNamesCannotEscapeAndHtmlGoesAsAPage() {
        assertEquals("secret.txt",safeShareName("../../secret.txt"));assertEquals("file",safeShareName(".."))
        assertEquals("test.html",safeShareName("C:\\test.html"));assertEquals("text/html",shareMime("test.html"));assertEquals("text/plain",shareMime("notes.md"))
        assertEquals("application/octet-stream",shareMime("opaque.bin"))
    }
}
