package io.github.xnovosx.kobraspoolman.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Bridge-Adresse und App-Schluessel, gespeichert auf dem Geraet (nicht in Backups, siehe Manifest). */
data class Connection(val url: String = "", val token: String = "") {
    val configured: Boolean get() = url.isNotBlank()
}

private val Context.store by preferencesDataStore(name = "settings")

class Settings(private val context: Context) {
    private val urlKey = stringPreferencesKey("bridge_url")
    private val tokenKey = stringPreferencesKey("app_token")

    val connection: Flow<Connection> = context.store.data.map {
        Connection(it[urlKey].orEmpty(), it[tokenKey].orEmpty())
    }

    suspend fun save(c: Connection) {
        context.store.edit {
            it[urlKey] = BridgeClient.normalizeUrl(c.url)
            it[tokenKey] = c.token.trim()
        }
    }
}
