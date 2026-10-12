package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.BuildConfig
import io.github.xnovosx.kobraspoolman.nfc.TagScanner
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono
import io.github.xnovosx.kobraspoolman.data.tr

@Composable
fun TagWriteScreen(
    spoolId: Int,
    job: AppViewModel.TagJob?,
    scanner: TagScanner,
    contentPadding: PaddingValues,
    onPrepare: () -> Unit,
    onCancel: () -> Unit,
) {
    LaunchedEffect(spoolId) { onPrepare() }
    Column(
        Modifier.fillMaxSize().background(K.Ground).verticalScroll(rememberScrollState())
            .padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp,
                bottom = contentPadding.calculateBottomPadding() + 20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            RoundIconButton(KIcons.Back, tr("Back"), onCancel)
            Text(if (job?.side == 2) tr("Tag 2 of 2") else tr("Tag 1 of 2"), style = MaterialTheme.typography.headlineSmall)
        }
        Box(Modifier.fillMaxWidth().padding(top = 16.dp), contentAlignment = Alignment.Center) {
            Box(Modifier.size(232.dp).clip(CircleShape).border(1.dp, K.AccentSoft, CircleShape), contentAlignment = Alignment.Center) {
                Box(Modifier.size(180.dp).clip(CircleShape).border(1.dp, K.Accent.copy(alpha = 0.3f), CircleShape),
                    contentAlignment = Alignment.Center) {
                    Box(Modifier.size(128.dp).clip(CircleShape).background(K.AccentSoft).border(2.dp, K.Accent, CircleShape),
                        contentAlignment = Alignment.Center) {
                        Icon(KIcons.Nfc, contentDescription = null, tint = K.Accent, modifier = Modifier.size(56.dp))
                    }
                }
            }
        }
        Text(when {
            job == null -> tr("Preparing the tag content …")
            job.side == 2 -> tr("Hold the second sticker to the phone")
            else -> tr("Hold the first sticker to the phone")
        },
            style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        Text(when {
            !scanner.nfcAvailable -> tr("This device has no NFC.")
            !scanner.nfcEnabled -> tr("NFC is switched off – switch it on in the Android settings.")
            else -> tr("Centre of the phone's back onto the sticker. Don't move until the message comes.")
        }, style = MaterialTheme.typography.bodyMedium, color = K.Muted, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth())

        if (job != null) {
            SectionLabel(tr("Being written"), Modifier.padding(top = 8.dp))
            val a = job.ace
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(K.Surface)
                .border(1.dp, K.Line, RoundedCornerShape(16.dp)).padding(horizontal = 14.dp, vertical = 4.dp)) {
                InfoRow(tr("Spool"), "#${job.spoolId}")
                InfoRow(tr("SKU / tag number"), a.sku)
                InfoRow(tr("Brand"), a.brand)
                InfoRow(tr("Material"), a.material)
                InfoRow(tr("Colour"), "#${a.color}", swatch = a.color)
                InfoRow(tr("Nozzle"), "${a.nozzleMin}–${a.nozzleMax} °C")
                InfoRow(tr("Bed"), "${a.bedMin}–${a.bedMax} °C")
                InfoRow(tr("Amount"), "${a.weightG} g · ${a.lengthM} m", last = true)
            }
            Hint(if (job.side == 2) tr("For the other spool side: the ACE 2 Pro reads only the side facing the reader. Both stickers get the same content.")
                 else tr("The ACE 2 Pro needs one sticker per spool side – the second one follows right after. Original Anycubic tags are write-protected – use empty NTAG213/215/216 stickers."))
            if (BuildConfig.DEBUG) {
                TextButton(onClick = { scanner.simulate(TagScanner.randomUid()) }, modifier = Modifier.fillMaxWidth()) {
                    Text(tr("Write a virtual tag (test without NFC)"), color = K.Accent)
                }
            }
        }
        SecondaryButton(if (job?.side == 2) tr("Done – only one tag") else tr("Write later"), onCancel, Modifier.fillMaxWidth())
    }
}

@Composable
private fun InfoRow(label: String, value: String, swatch: String? = null, last: Boolean = false) {
    Column {
        Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.bodyMedium, color = K.Muted, modifier = Modifier.weight(1f))
            if (swatch != null) {
                SpoolDisc(swatch, 16.dp)
                Text(" ", style = MaterialTheme.typography.bodyMedium)
            }
            Text(value, fontFamily = PlexMono, style = MaterialTheme.typography.bodyMedium)
        }
        if (!last) Box(Modifier.fillMaxWidth().size(width = 0.dp, height = 1.dp).background(K.Surface2))
    }
}
