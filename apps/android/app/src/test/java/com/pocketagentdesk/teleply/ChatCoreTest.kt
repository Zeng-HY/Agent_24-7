package com.pocketagentdesk.teleply

import org.junit.Test
import org.junit.Assert.*
import org.json.JSONObject

class ChatCoreTest {
    @Test fun reconnectCannotRegressTerminalTurnButNewTurnCanRun() {
        val done=Control(available=true,turns=mapOf("t" to "completed"))
        assertFalse(mergeControl(done,Control(true,true,"t",turns=mapOf("t" to "inProgress"))).running)
        assertTrue(mergeControl(done,Control(true,true,"new",turns=mapOf("new" to "inProgress"))).running)
    }
    private fun frame(seq:Int,type:String="update",chat:String="c")=JSONObject("""{"protocol":1,"app":"codex","id":"$chat","type":"$type","seq":$seq,"chat":{"id":"$chat","app":"codex","messages":[]},"messages":[]}""")
    @Test fun sequenceRestartsOnlyWithSnapshotAndDeduplicates() {
        val r=StreamReducer("c")
        assertNotNull(r.accept(frame(1,"snapshot")));assertNull(r.accept(frame(1,"snapshot")));assertNotNull(r.accept(frame(2)))
        assertThrows(IllegalArgumentException::class.java) { r.accept(frame(4)) }
        assertNotNull(StreamReducer("c").accept(frame(1,"snapshot")))
    }
    @Test fun rejectsWrongIdentityAndMissingSnapshot() {
        assertThrows(IllegalArgumentException::class.java) { StreamReducer("c").accept(frame(1,"snapshot","other")) }
        assertThrows(IllegalArgumentException::class.java) { StreamReducer("c").accept(frame(1)) }
    }
    @Test fun committedAliasReplacesLiveAndUsesSourceOrder() {
        val old=listOf(Message("first","assistant","same",order=1.0),Message("live","assistant","same",order=3.0))
        val result=mergeLive(old,listOf(Message("committed","assistant","same",order=2.0,aliases=listOf("live"))))
        assertEquals(listOf("first","committed"),result.map { it.id })
    }
    @Test fun messageOpenedWholeStaysWholeUntilItGrows() {
        val cut=Message("u","user","前",truncated=true,request="r1",length=3);val full=Message("u","user","前后全",length=3)
        val kept=keepWhole(listOf(cut),mapOf("u" to full)).single()
        assertEquals("前后全",kept.text);assertFalse(kept.truncated);assertEquals("r1",kept.request)
        val grown=cut.copy(length=5);assertEquals(listOf(grown),keepWhole(listOf(grown),mapOf("u" to full)))
        assertEquals("展开全文",expandLabel(Message("a","assistant","")))
    }
    @Test fun unknownAndQueueAreNotDelivery() {
        assertEquals("送达状态待确认",receiptLabel("unknown",JSONObject(),"send"))
        assertEquals("已排队",receiptLabel("queued",JSONObject(),"send"))
        assertEquals("已接收",receiptLabel("accepted",JSONObject(),"send"))
        assertEquals("已送达",receiptLabel("accepted",JSONObject("""{"evidence":{"source":"conversation_record"}}"""),"send"))
        assertTrue(receiptLabel("accepted",JSONObject(),"stop").contains("等待"))
    }
}
