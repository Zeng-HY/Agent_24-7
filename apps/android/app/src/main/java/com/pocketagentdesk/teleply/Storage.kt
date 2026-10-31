package com.pocketagentdesk.teleply

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import androidx.room.*
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.settings by preferencesDataStore("native_settings")
data class Preferences(val origin: String = "", val theme: String = "system", val dynamic: Boolean = false, val scope: String = "", val device: String = "", val chat: String = "", val title: String = "", val app:String="codex")
class SettingsStore(private val context: Context) {
    val flow = context.settings.data.map { p -> Preferences(p[stringPreferencesKey("origin")] ?: "", p[stringPreferencesKey("theme")] ?: "system", p[booleanPreferencesKey("dynamic")] ?: false, p[stringPreferencesKey("scope")] ?: "", p[stringPreferencesKey("device")] ?: "", p[stringPreferencesKey("chat")] ?: "", p[stringPreferencesKey("title")] ?: "",p[stringPreferencesKey("app")] ?: "codex") }
    suspend fun source(app:String) { context.settings.edit { it[stringPreferencesKey("app")]=app;it.remove(stringPreferencesKey("chat"));it.remove(stringPreferencesKey("title")) } }
    suspend fun origin(value: String) { context.settings.edit { p -> p[stringPreferencesKey("origin")] = value; listOf("scope","device","chat","title","app").forEach { p.remove(stringPreferencesKey(it)) } } }
    suspend fun appearance(theme: String, dynamic: Boolean) { context.settings.edit { it[stringPreferencesKey("theme")] = theme; it[booleanPreferencesKey("dynamic")] = dynamic } }
    suspend fun selection(scope: String, device: String, chat: String = "", title: String = "") { context.settings.edit { p -> mapOf("scope" to scope,"device" to device,"chat" to chat).forEach { (k,v) -> p[stringPreferencesKey(k)] = v }; p.remove(stringPreferencesKey("title")) } }
    /** 10-31 ([moveService]): whether the move off the old default ran; then that it did, with only the address changed. */
    suspend fun serviceMoved() = context.settings.data.first()[booleanPreferencesKey("service_moved")] == true
    suspend fun serviceMoved(origin: String?) { context.settings.edit { p -> if (origin != null) p[stringPreferencesKey("origin")] = origin; p[booleanPreferencesKey("service_moved")] = true } }
}

/**
 * 10-31: Teleply's own service moved from its IP ([OldDefaultOrigin]) to its domain ([DefaultOrigin]). It answers on
 * both and a sign-in is good on either, but this phone keeps the sign-in by address ([SecureCookieVault]). Once, as the
 * app starts: a phone still on the old default (its IP saved, or nothing saved, which meant the default) is put on the
 * new one, with its sign-in moved to the new address and the conversation it checks in the background ([watched]).
 * Where it was (the sign-in's scope, the computer, the conversation), drafts and sends are kept by sign-in, not by
 * address, so they stay as they are; updates come from addresses of their own. Done is remembered: the IP set again by
 * hand (开发者选项 → 服务地址) stays.
 */
suspend fun moveService(store: ReaderStore, vault: CookieVault, watched: (from: String, to: String) -> Unit = { _, _ -> }) {
    if (store.serviceMoved()) return
    val from = serviceOrigin(OldDefaultOrigin).toString()
    val to = serviceOrigin(DefaultOrigin).toString()
    val saved = store.preferences().origin
    val old = saved.isBlank() || sameService(saved, from)
    if (old) {
        vault.read(from)?.let { vault.write(to, it); vault.write(from, null) }
        watched(from, to)
    }
    // Nothing saved stays nothing: the default, which is now the domain.
    store.serviceMoved(if (old && saved.isNotBlank()) to else null)
}
class SecureCookieVault(context: Context) : CookieVault {
    private val prefs = context.getSharedPreferences("keystore_credentials", Context.MODE_PRIVATE)
    private val alias = "teleply.account.v1"
    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        return (ks.getKey(alias, null) as? SecretKey) ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    private fun id(origin: String) = MessageDigest.getInstance("SHA-256").digest(origin.toByteArray()).joinToString("") { "%02x".format(it) }
    @Synchronized override fun read(origin: String): String? {
        val raw = prefs.getString(id(origin), null) ?: return null
        return try {
            val parts = raw.split(":")
            Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)))
                updateAAD(origin.toByteArray())
                String(doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), Charsets.UTF_8)
            }
        } catch (_: Exception) { prefs.edit().remove(id(origin)).commit(); null }
    }
    @Synchronized override fun write(origin: String, cookie: String?) {
        if (cookie == null) { check(prefs.edit().remove(id(origin)).commit()); return }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()); updateAAD(origin.toByteArray()) }
        val encrypted = cipher.doFinal(cookie.toByteArray())
        check(prefs.edit().putString(id(origin), Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
    }
}
// Private app storage; no transcript cache. Backups remain disabled.
@Entity(tableName="chat_draft", primaryKeys=["scope","device","app","chat"])
data class ChatDraft(val scope:String,val device:String,val app:String="codex",val chat:String,val text:String)
@Entity(tableName="chat_submission", primaryKeys=["request"])
data class Submission(val request:String,val scope:String,val device:String,val app:String="codex",val chat:String,val text:String,val action:String,val turn:String,val body:String,val label:String="提交中",val created:Long=System.currentTimeMillis())
@Entity(tableName = "reading_position", primaryKeys = ["scope", "device", "app", "chat"])
data class ReadingPosition(val scope: String, val device: String, val app: String = "codex", val chat: String, val message: String, val offset: Int)
@Entity(tableName="interaction_draft",primaryKeys=["scope","device","app","chat","kind"])
data class InteractionDraft(val scope:String,val device:String,val app:String,val chat:String,val kind:String,val value:String)
@Dao interface ReadingDao {
    @Query("SELECT value FROM interaction_draft WHERE scope=:scope AND device=:device AND app=:app AND chat=:chat AND kind=:kind") suspend fun detail(scope:String,device:String,app:String,chat:String,kind:String):String?
    @Insert(onConflict=OnConflictStrategy.REPLACE) suspend fun detail(value:InteractionDraft)
    @Query("SELECT * FROM chat_draft WHERE scope=:scope AND device=:device AND app=:app AND chat=:chat") suspend fun draft(scope:String,device:String,chat:String,app:String="codex"):ChatDraft?
    @Insert(onConflict=OnConflictStrategy.REPLACE) suspend fun draft(value:ChatDraft)
    @Query("SELECT * FROM chat_submission WHERE scope=:scope AND device=:device AND app=:app AND chat=:chat ORDER BY created DESC") suspend fun submissions(scope:String,device:String,chat:String,app:String="codex"):List<Submission>
    @Insert(onConflict=OnConflictStrategy.REPLACE) suspend fun submission(value:Submission)
    @Transaction suspend fun begin(value:Submission) {
        submission(value)
        if(value.action=="send") draft(ChatDraft(value.scope,value.device,app=value.app,chat=value.chat,text=""))
    }
    @Query("SELECT * FROM reading_position WHERE scope=:scope AND device=:device AND app=:app AND chat=:chat") suspend fun find(scope: String, device: String, chat: String,app:String="codex"): ReadingPosition?
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun save(position: ReadingPosition)
    @Query("DELETE FROM reading_position WHERE scope=:scope") suspend fun clear(scope: String)
}
@Database(entities = [ReadingPosition::class,ChatDraft::class,Submission::class,InteractionDraft::class], version = 3, exportSchema = true)
abstract class ReadingDatabase : RoomDatabase() { abstract fun positions(): ReadingDao }
val CHAT_MIGRATION=object:androidx.room.migration.Migration(1,2) {
    override fun migrate(db:androidx.sqlite.db.SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS chat_draft (scope TEXT NOT NULL, device TEXT NOT NULL, app TEXT NOT NULL, chat TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY(scope,device,app,chat))")
        db.execSQL("CREATE TABLE IF NOT EXISTS chat_submission (request TEXT NOT NULL, scope TEXT NOT NULL, device TEXT NOT NULL, app TEXT NOT NULL, chat TEXT NOT NULL, text TEXT NOT NULL, action TEXT NOT NULL, turn TEXT NOT NULL, body TEXT NOT NULL, label TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY(request))")
    }
}

val INTERACTION_MIGRATION=object:androidx.room.migration.Migration(2,3) {
    override fun migrate(db:androidx.sqlite.db.SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS interaction_draft (scope TEXT NOT NULL, device TEXT NOT NULL, app TEXT NOT NULL, chat TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(scope,device,app,chat,kind))")
    }
}
