package io.github.xnovosx.kobraspoolman

import android.app.Application
import android.content.Context
import android.content.res.Configuration
import io.github.xnovosx.kobraspoolman.data.I18n

/** Application: sets the language of the texts (I18n) at start and whenever the locale changes. */
class KobraApp : Application() {
    override fun onCreate() {
        super.onCreate()
        applyLanguage(this)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        applyLanguage(this)
    }

    companion object {
        /** Language of the app's configuration (system or per-app language) -> I18n. Cheap if unchanged. */
        fun applyLanguage(context: Context) {
            val lang = I18n.langOf(context.resources.configuration.locales[0]?.toLanguageTag())
            if (lang == I18n.lang) return
            val json = if (lang == "en") null else
                runCatching { context.assets.open("i18n/$lang.json").bufferedReader().use { it.readText() } }.getOrNull()
            I18n.use(lang, json)
        }
    }
}
