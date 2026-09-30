package io.github.xnovosx.kobraspoolman

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
        // Immer dunkles Design -> helle Symbole in den Systemleisten, auch wenn das Handy hell eingestellt ist
        enableEdgeToEdge(SystemBarStyle.dark(Color.TRANSPARENT), SystemBarStyle.dark(Color.TRANSPARENT))
        setContent { KobraTheme { AppRoot(vm, scanner) } }
    }

    // NFC nur im Vordergrund: Reader-Modus faengt jeden Tag ab, solange die App offen ist
    override fun onResume() {
        super.onResume()
        scanner.resume(this)
    }

    override fun onPause() {
        scanner.pause(this)
        super.onPause()
    }
}
