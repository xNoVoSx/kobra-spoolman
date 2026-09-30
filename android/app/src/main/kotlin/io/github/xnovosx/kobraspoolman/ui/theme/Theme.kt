package io.github.xnovosx.kobraspoolman.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import io.github.xnovosx.kobraspoolman.R

// Werkstatt-Look aus den Entwuerfen: dunkler Grund, Bernstein als Akzent, Spulenfarben als Hauptfarben.
object K {
    val Ground = Color(0xFF101215)
    val Surface = Color(0xFF191C21)
    val Surface2 = Color(0xFF22262C)
    val Sunken = Color(0xFF15181C)
    val Line = Color(0xFF2E333A)
    val LineStrong = Color(0xFF3A4048)
    val Text = Color(0xFFECEEF1)
    val Muted = Color(0xFF9AA3AE)
    val Faint = Color(0xFF4B525C)
    val Accent = Color(0xFFF5B83D)
    val OnAccent = Color(0xFF1A1405)
    val AccentSoft = Color(0xFF2B2412)
    val Danger = Color(0xFFF87171)
    val DangerText = Color(0xFFFCA5A5)
    val DangerSoft = Color(0xFF1E1414)
    val DangerLine = Color(0xFF5A2A2A)
    val Ok = Color(0xFF4ADE80)
}

/** Farben der Statuskarte je Druckerzustand. */
data class StatusColors(val dot: Color, val fg: Color, val bg: Color, val line: Color)

fun statusColors(state: String): StatusColors = when (state) {
    "printing" -> StatusColors(Color(0xFF4ADE80), Color(0xFF86EFAC), Color(0xFF16231C), Color(0xFF24503A))
    "paused", "changing" -> StatusColors(K.Accent, Color(0xFFFCD58A), Color(0xFF1D1A12), Color(0xFF4B3B12))
    "error", "cancelled" -> StatusColors(K.Danger, K.DangerText, K.DangerSoft, K.DangerLine)
    "offline" -> StatusColors(Color(0xFF6B7280), Color(0xFFC9CFD6), Color(0xFF16181B), K.Line)
    else -> StatusColors(Color(0xFF60A5FA), Color(0xFFBFDBFE), Color(0xFF141C28), Color(0xFF233A5A))
}

/** "685BC7" -> Farbe; ungueltig -> neutrales Grau. */
fun spoolColor(hex: String?): Color {
    val h = hex?.trim()?.removePrefix("#")?.take(6) ?: return K.Surface2
    return h.toLongOrNull(16)?.takeIf { h.length == 6 }?.let { Color(0xFF000000 or it) } ?: K.Surface2
}

/** Dunkle Kopffarbe aus der Spulenfarbe (fuer die Spulenkarte), heller Text bleibt lesbar. */
fun headerTint(c: Color): Color {
    val f = if (c.luminance() > 0.5f) 0.22f else 0.35f
    return Color(c.red * f + 0.04f, c.green * f + 0.04f, c.blue * f + 0.05f)
}

private fun variable(res: Int, weight: Int) =
    Font(res, FontWeight(weight), variationSettings = FontVariation.Settings(FontVariation.weight(weight)))

val Grotesk = FontFamily(variable(R.font.space_grotesk, 500), variable(R.font.space_grotesk, 600), variable(R.font.space_grotesk, 700))
val Plex = FontFamily(variable(R.font.plex_sans, 400), variable(R.font.plex_sans, 500), variable(R.font.plex_sans, 600))
val PlexMono = FontFamily(Font(R.font.plex_mono_medium, FontWeight.Medium), Font(R.font.plex_mono_semibold, FontWeight.SemiBold))

private val typography = Typography(
    headlineMedium = TextStyle(fontFamily = Grotesk, fontWeight = FontWeight.Bold, fontSize = 28.sp, letterSpacing = (-0.5).sp),
    headlineSmall = TextStyle(fontFamily = Grotesk, fontWeight = FontWeight.Bold, fontSize = 22.sp),
    titleLarge = TextStyle(fontFamily = Grotesk, fontWeight = FontWeight.SemiBold, fontSize = 18.sp),
    titleMedium = TextStyle(fontFamily = Grotesk, fontWeight = FontWeight.Bold, fontSize = 16.sp),
    titleSmall = TextStyle(fontFamily = Grotesk, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, letterSpacing = 0.6.sp),
    bodyLarge = TextStyle(fontFamily = Plex, fontSize = 16.sp),
    bodyMedium = TextStyle(fontFamily = Plex, fontSize = 14.sp),
    bodySmall = TextStyle(fontFamily = Plex, fontSize = 12.sp),
    labelLarge = TextStyle(fontFamily = Plex, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
    labelMedium = TextStyle(fontFamily = Plex, fontWeight = FontWeight.Medium, fontSize = 13.sp),
    labelSmall = TextStyle(fontFamily = Plex, fontWeight = FontWeight.SemiBold, fontSize = 11.sp),
)

@Composable
fun KobraTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = K.Accent, onPrimary = K.OnAccent, background = K.Ground, onBackground = K.Text,
            surface = K.Surface, onSurface = K.Text, surfaceVariant = K.Surface2, onSurfaceVariant = K.Muted,
            outline = K.LineStrong, outlineVariant = K.Line, error = K.Danger, surfaceContainer = K.Surface,
            surfaceContainerHigh = K.Surface2, surfaceContainerLow = K.Sunken,
        ),
        typography = typography,
        content = content,
    )
}
