package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.Catalog
import io.github.xnovosx.kobraspoolman.data.FilamentInfo
import io.github.xnovosx.kobraspoolman.data.NewSpool
import io.github.xnovosx.kobraspoolman.ui.theme.K

@Composable
fun NewSpoolScreen(
    catalog: Catalog?,
    slots: Int,
    tagUid: String?,
    canWrite: Boolean,
    busy: Boolean,
    contentPadding: PaddingValues,
    preselect: Int?,
    onLoad: () -> Unit,
    onNewFilament: () -> Unit,
    onCancel: () -> Unit,
    onCreate: (NewSpool) -> Unit,
) {
    LaunchedEffect(Unit) { onLoad() }
    var query by rememberSaveable { mutableStateOf("") }
    var selectedId by rememberSaveable { mutableStateOf<Int?>(null) }
    var weight by rememberSaveable { mutableStateOf("") }
    var spoolWeight by rememberSaveable { mutableStateOf("") }
    var slot by rememberSaveable { mutableStateOf<Int?>(null) }
    LaunchedEffect(preselect) { if (preselect != null) selectedId = preselect }
    val selected = catalog?.filaments?.firstOrNull { it.filamentId == selectedId }
    // Gewichte aus dem Filament vorschlagen, sobald eins gewaehlt ist
    LaunchedEffect(selectedId) {
        selected?.let { f ->
            weight = f.weight?.toInt()?.toString().orEmpty()
            spoolWeight = f.spoolWeight?.toInt()?.toString().orEmpty()
        }
    }
    val list = remember(catalog, query) {
        val q = query.trim().lowercase()
        catalog?.filaments.orEmpty().filter { q.isEmpty() || "${it.displayName} ${it.material}".lowercase().contains(q) }
    }

    Column(Modifier.fillMaxSize().background(K.Ground).imePadding()) {
        Column(Modifier.padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                RoundIconButton(KIcons.Close, "Abbrechen", onCancel)
                Text("Neue Spule", style = MaterialTheme.typography.headlineSmall)
            }
            if (tagUid != null) Hint("Wird mit dem gescannten Tag $tagUid verknüpft.")
            OutlinedTextField(
                value = query, onValueChange = { query = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("Filament suchen") }, shape = RoundedCornerShape(14.dp),
                leadingIcon = { Icon(KIcons.Search, contentDescription = null, tint = K.Muted) },
            )
        }
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (catalog == null) item { Text("Lade Filamente …", color = K.Muted) }
            items(list, key = { it.filamentId }) { f ->
                FilamentRow(f, selected = f.filamentId == selectedId) { selectedId = f.filamentId }
            }
            if (catalog != null && list.isEmpty()) item {
                Text("Nichts gefunden.", style = MaterialTheme.typography.bodySmall, color = K.Muted)
            }
            item {
                OutlinedButton(onClick = onNewFilament, enabled = canWrite, modifier = Modifier.fillMaxWidth().height(52.dp),
                    shape = RoundedCornerShape(16.dp), border = BorderStroke(1.dp, K.Faint)) {
                    Icon(KIcons.Plus, contentDescription = null, tint = K.Accent, modifier = Modifier.size(18.dp))
                    Text("  Nicht dabei? Neues Filament", color = K.Accent, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp)).background(K.Surface)
                .border(1.dp, K.Line, RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp))
                .padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = contentPadding.calculateBottomPadding() + 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                NumberField("Anfangsgewicht (g)", weight, { weight = it }, Modifier.weight(1f))
                NumberField("Leerspule (g)", spoolWeight, { spoolWeight = it }, Modifier.weight(1f))
            }
            Text("Direkt einlegen", style = MaterialTheme.typography.bodySmall, color = K.Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Choice("Regal", slot == null, Modifier.weight(1.4f)) { slot = null }
                (1..slots).forEach { n -> Choice("$n", slot == n, Modifier.weight(1f)) { slot = n } }
            }
            PrimaryButton(
                if (tagUid != null) "Anlegen und Tag verknüpfen" else "Spule anlegen",
                onClick = {
                    selected?.let { f ->
                        onCreate(NewSpool(f.filamentId, weight.toDoubleOrNull(), spoolWeight.toDoubleOrNull(), slot))
                    }
                },
                modifier = Modifier.fillMaxWidth(), enabled = canWrite && !busy && selected != null,
            )
            if (!canWrite) Hint("Anlegen geht erst, wenn die App gekoppelt ist (Einstellungen).")
        }
    }
}

@Composable
private fun FilamentRow(f: FilamentInfo, selected: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).clip(shape).background(if (selected) K.AccentSoft else K.Surface)
            .border(if (selected) 2.dp else 1.dp, if (selected) K.Accent else K.Line, shape)
            .clickable(role = Role.RadioButton, onClick = onClick).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        SpoolDisc(f.color, 40.dp)
        Column(Modifier.weight(1f)) {
            Text(f.displayName, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(listOfNotNull(f.material, f.nozzleTemp?.let { "${it.toInt()} °C" }, "${f.spools} Spule(n)").joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
        if (selected) Icon(KIcons.Check, contentDescription = "gewählt", tint = K.Accent, modifier = Modifier.size(22.dp))
    }
}

@Composable
private fun NumberField(label: String, value: String, onChange: (String) -> Unit, modifier: Modifier) {
    OutlinedTextField(
        value = value, onValueChange = { v -> onChange(v.filter { it.isDigit() || it == '.' || it == ',' }.replace(',', '.')) },
        label = { Text(label) }, singleLine = true, modifier = modifier, shape = RoundedCornerShape(12.dp),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
    )
}

@Composable
private fun Choice(text: String, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, modifier = modifier.height(44.dp), shape = RoundedCornerShape(12.dp),
        contentPadding = PaddingValues(0.dp),
        border = BorderStroke(if (selected) 2.dp else 1.dp, if (selected) K.Accent else K.LineStrong),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = if (selected) K.AccentSoft else K.Ground,
            contentColor = if (selected) K.Accent else K.Text),
    ) { Text(text, style = MaterialTheme.typography.labelLarge) }
}
