package io.github.xnovosx.kobraspoolman

import android.content.Intent
import android.os.Bundle
import android.graphics.Color
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import io.github.xnovosx.kobraspoolman.nfc.TagScanner
import io.github.xnovosx.kobraspoolman.ui.AppRoot
import io.github.xnovosx.kobraspoolman.ui.AppViewModel
import io.github.xnovosx.kobraspoolman.ui.theme.KobraTheme

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()
    private val scanner = TagScanner()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // the per-app language may have changed (Android recreates the activity) - texts follow it
        KobraApp.applyLanguage(this)
        // Always the dark theme -> light icons in the system bars, even when the phone is set to light
        enableEdgeToEdge(SystemBarStyle.dark(Color.TRANSPARENT), SystemBarStyle.dark(Color.TRANSPARENT))
        setContent { KobraTheme { AppRoot(vm, scanner) } }
        if (savedInstanceState == null) openLink(intent)
    }

    // a Spoolman QR code from the phone camera (web+spoolman:...) while the app is already open (singleTop)
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        openLink(intent)
    }

    private fun openLink(intent: Intent?) {
        val uri = intent?.takeIf { it.action == Intent.ACTION_VIEW }?.dataString ?: return
        if (uri.startsWith("web+spoolman:", ignoreCase = true)) vm.onQr(uri)
    }

    // NFC only in the foreground: reader mode catches every tag while the app is open
    override fun onResume() {
        super.onResume()
        scanner.resume(this)
    }

    override fun onPause() {
        scanner.pause(this)
        super.onPause()
    }
}
