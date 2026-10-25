package com.pocketagentdesk.teleply
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import android.content.Context
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35],application=android.app.Application::class)
class ReadingDatabaseTest {
    @Test fun migratesV1WithoutLosingAnchorAndPersistsIsolatedDrafts()=runBlocking {
        val context=ApplicationProvider.getApplicationContext<Context>()
        // Short: Windows paths stop at 260 characters, and the test temp folder and package name take most of them.
        val name="m${java.util.UUID.randomUUID().toString().take(8)}.db"
        context.openOrCreateDatabase(name,0,null).use { old ->
            old.execSQL("CREATE TABLE reading_position (scope TEXT NOT NULL, device TEXT NOT NULL, app TEXT NOT NULL, chat TEXT NOT NULL, message TEXT NOT NULL, offset INTEGER NOT NULL, PRIMARY KEY(scope,device,app,chat))")
            old.execSQL("INSERT INTO reading_position VALUES ('owner','device','codex','chat','m',45)")
            old.version=1
        }
        var db=Room.databaseBuilder(context,ReadingDatabase::class.java,name).addMigrations(CHAT_MIGRATION,INTERACTION_MIGRATION).build()
        try {
            assertEquals(45,db.positions().find("owner","device","chat")!!.offset)
            db.positions().draft(ChatDraft("owner","device",chat="chat",text="草稿"))
            val record=Submission("r","owner","device",chat="chat",text="提交快照",action="send",turn="t",body="{}")
            db.positions().begin(record)
            db.positions().draft(ChatDraft("owner","device",chat="chat",text="后续草稿"))
            db.close();db=Room.databaseBuilder(context,ReadingDatabase::class.java,name).addMigrations(CHAT_MIGRATION,INTERACTION_MIGRATION).build()
            assertEquals("后续草稿",db.positions().draft("owner","device","chat")!!.text)
            db.positions().draft(ChatDraft("owner","device",app="deepseek",chat="chat",text="另一个来源"))
            db.positions().detail(InteractionDraft("owner","device","codex","chat","workspace","{\"first_message\":\"test\"}"))
            assertEquals("后续草稿",db.positions().draft("owner","device","chat","codex")!!.text)
            assertEquals("另一个来源",db.positions().draft("owner","device","chat","deepseek")!!.text)
            assertNull(db.positions().detail("owner","device","deepseek","chat","workspace"))
            assertEquals("提交快照",db.positions().submissions("owner","device","chat").single().text)
            assertNull(db.positions().draft("other","device","chat"));assertTrue(db.positions().submissions("owner","other","chat").isEmpty())
        } finally { db.close();context.deleteDatabase(name) }
    }
    @Test fun persistsPositionAcrossReopenWithIdentityIsolation()=runBlocking {
        val context=ApplicationProvider.getApplicationContext<Context>()
        val name="reading-test-${java.util.UUID.randomUUID()}.db"
        var db=Room.databaseBuilder(context,ReadingDatabase::class.java,name).build()
        try {
            db.positions().save(ReadingPosition("ownerA","computerA",chat="sameChat",message="m17",offset=45))
            db.close();db=Room.databaseBuilder(context,ReadingDatabase::class.java,name).build()
            assertEquals(45,db.positions().find("ownerA","computerA","sameChat")!!.offset)
            assertNull(db.positions().find("ownerB","computerA","sameChat"))
            assertNull(db.positions().find("ownerA","computerB","sameChat"))
            assertNull(db.positions().find("ownerA","computerA","otherChat"))
        } finally { db.close();context.deleteDatabase(name) }
    }
}
