package io.github.xnovosx.kobraspoolman.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.github.xnovosx.kobraspoolman.data.Catalog
import io.github.xnovosx.kobraspoolman.data.FieldSpec
import io.github.xnovosx.kobraspoolman.data.FilamentDraft
import io.github.xnovosx.kobraspoolman.data.FilamentForm
import io.github.xnovosx.kobraspoolman.data.Kind
import io.github.xnovosx.kobraspoolman.data.placeholder
import io.github.xnovosx.kobraspoolman.data.templateFor
import io.github.xnovosx.kobraspoolman.ui.theme.K
import io.github.xnovosx.kobraspoolman.ui.theme.PlexMono

private val STEPS = listOf("Produkt", "Farbe", "Material & Gewicht", "Temperaturen", "Kühlung",
    "Extrusion & Retraction", "Übersicht")

private val REQUIRED = setOf("name", "material", "vendor")

/** Gaengige Filamentfarben als Schnellauswahl. */
private val PALETTE = listOf("FFFFFF", "F2F2F2", "C0C0C0", "808080", "212721", "000000", "D32F2F", "F57C00",
    "FBC02D", "388E3C", "3FA46A", "52D2BC", "1976D2", "685BC7", "7B1FA2", "C52E79", "8D6E63", "E8C9A0")

@Composable
fun FilamentScreen(
    catalog: Catalog?,
    canWrite: Boolean,
    busy: Boolean,
    contentPadding: PaddingValues,
    onLoad: () -> Unit,
    onCancel: () -> Unit,
    onCreate: (FilamentDraft, List<FieldSpec>) -> Unit,
) {
    LaunchedEffect(Unit) { onLoad() }
    var step by rememberSaveable { mutableIntStateOf(0) }
    var draft by remember { mutableStateOf(FilamentDraft()) }
    val fields = catalog?.fields.orEmpty()
    val specs = remember(fields) { FilamentForm.all(fields) }
    val tpl = templateFor(draft, catalog?.templates.orEmpty())
    val errors = draft.errors(specs)
    val stepHasError = when (step) {
        0 -> listOf("name", "material", "vendor").any { it in errors }
        1 -> "color" in errors
        else -> specsFor(step, fields).any { it.key in errors }
    }

    Column(Modifier.fillMaxSize().background(K.Ground).imePadding()) {
        Column(Modifier.padding(start = 20.dp, end = 20.dp, top = contentPadding.calculateTopPadding() + 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                RoundIconButton(KIcons.Close, "Abbrechen", onCancel)
                Column {
                    Text("Neues Filament · Schritt ${step + 1} von ${STEPS.size}", style = MaterialTheme.typography.bodySmall,
                        color = K.Muted)
                    Text(STEPS[step], style = MaterialTheme.typography.headlineSmall)
                }
            }
            FillBar((step + 1f) / STEPS.size, height = 4.dp, track = K.Line)
            DraftHeader(draft, tpl?.name)
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (catalog == null) { Text("Lade …", color = K.Muted); return@Column }
            when (step) {
                // Fehlende Pflichtfelder nicht rot anzeigen - "Weiter" bleibt einfach aus, bis sie gesetzt sind
                0 -> ProductStep(draft, catalog, errors - REQUIRED) { draft = it }
                1 -> ColorStep(draft, errors) { draft = it }
                6 -> SummaryStep(draft, specs, fields, tpl?.name) { draft = it }
                else -> {
                    InheritLegend(tpl?.name, draft.orcaBasis)
                    specsFor(step, fields).forEach { s ->
                        FieldRow(s, draft.value(s.key), placeholder(tpl, s), errors[s.key]) { draft = draft.with(s.key, it) }
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth().background(K.Sunken).padding(start = 20.dp, end = 20.dp, top = 12.dp,
            bottom = contentPadding.calculateBottomPadding() + 16.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SecondaryButton(if (step == 0) "Abbrechen" else "Zurück", { if (step == 0) onCancel() else step-- },
                Modifier.weight(1f))
            if (step < STEPS.lastIndex) {
                PrimaryButton("Weiter", { step++ }, Modifier.weight(1.4f), enabled = !stepHasError)
            } else {
                PrimaryButton("Filament anlegen", { onCreate(draft, specs) }, Modifier.weight(1.4f),
                    enabled = canWrite && !busy && errors.isEmpty())
            }
        }
    }
}

private fun specsFor(step: Int, fields: List<io.github.xnovosx.kobraspoolman.data.ExtraField>): List<FieldSpec> = when (step) {
    2 -> FilamentForm.group(FilamentForm.PHYSICAL, fields)
    3 -> FilamentForm.group(FilamentForm.TEMPS, fields)
    4 -> FilamentForm.group(FilamentForm.COOLING, fields)
    5 -> FilamentForm.group(FilamentForm.EXTRUSION, fields) + FilamentForm.others(fields)
    else -> emptyList()
}

@Composable
private fun DraftHeader(d: FilamentDraft, template: String?) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(K.Surface).border(1.dp, K.Line, RoundedCornerShape(14.dp))
        .padding(10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        SpoolDisc(d.colorHex.removePrefix("#").ifBlank { null }, 28.dp)
        Column(Modifier.weight(1f)) {
            Text(d.name.ifBlank { "Neues Filament" }, style = MaterialTheme.typography.bodyMedium)
            Text(listOfNotNull(d.material.ifBlank { null }, d.orcaBasis.ifBlank { null } ?: template).joinToString(" · ")
                .ifBlank { "Material noch offen" }, style = MaterialTheme.typography.bodySmall, color = K.Muted)
        }
    }
}

@Composable
private fun InheritLegend(template: String?, orcaBasis: String) {
    val from = when {
        orcaBasis.isNotBlank() -> "dem Orca-Profil „$orcaBasis“"
        template != null -> "der $template"
        else -> "Orcas Standardprofil"
    }
    Hint("Leer lassen = Wert aus $from. Grau steht, was dann gilt. Gespeichert wird nur, was du einträgst.")
}

@Composable
private fun ProductStep(d: FilamentDraft, cat: Catalog, errors: Map<String, String>, set: (FilamentDraft) -> Unit) {
    SectionLabel("Hersteller")
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        cat.vendors.forEach { v ->
            Pill(v.name, d.vendorId == v.id && d.newVendor.isBlank()) { set(d.copy(vendorId = v.id, newVendor = "")) }
        }
    }
    TextInput("…oder neuer Hersteller", d.newVendor, { set(d.copy(newVendor = it, vendorId = if (it.isBlank()) d.vendorId else null)) })
    TextInput("Name (ohne Hersteller), z.B. PETG 2.0 Mintgrün", d.name, { set(d.copy(name = it)) }, error = errors["name"])

    SectionLabel("Material", Modifier.padding(top = 6.dp))
    val materials = cat.templates.map { it.material.uppercase() }.distinct()
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        materials.forEach { m -> Pill(m, d.material.equals(m, true)) { set(d.copy(material = m)) } }
    }
    TextInput("…oder anderes Material", d.material.takeIf { m -> materials.none { it.equals(m, true) } }.orEmpty(),
        { set(d.copy(material = it)) }, error = errors["material"])

    SectionLabel("Vorlage", Modifier.padding(top = 6.dp))
    val auto = templateFor(d.copy(values = d.values - "vorlage"), cat.templates)?.name
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Pill("Automatisch" + (auto?.let { ": $it" } ?: ""), d.template.isBlank()) { set(d.with("vorlage", "")) }
        cat.templates.filter { d.material.isBlank() || it.material.equals(d.material, true) }.forEach { t ->
            Pill(t.name, d.template == t.name) { set(d.with("vorlage", t.name)) }
        }
    }

    SectionLabel("Eigenes Orca-Profil (optional)", Modifier.padding(top = 6.dp))
    TextInput("z.B. Sunlu PETG @System – ersetzt die Vorlage", d.orcaBasis, { set(d.with("orca_basis", it)) })
    val q = d.orcaBasis.trim()
    if (q.length >= 2) {
        cat.orcaBases.filter { it.contains(q, true) && it != q }.take(6).forEach { name ->
            Text(name, style = MaterialTheme.typography.bodyMedium, color = K.Accent,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { set(d.with("orca_basis", name)) }
                    .padding(horizontal = 8.dp, vertical = 8.dp))
        }
        if (cat.orcaBases.isEmpty()) Text("Keine Liste – das Orca-Plugin meldet die Profile beim nächsten Sync.",
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
    }

    val sameVendor = cat.filaments.filter { d.vendorId == null || it.vendorId == d.vendorId }
    if (sameVendor.isNotEmpty()) {
        SectionLabel("Werte übernehmen von …", Modifier.padding(top = 6.dp))
        Text("Für eine neue Farbe derselben Produktreihe: Temperaturen, Lüfter, Flow usw. werden kopiert.",
            style = MaterialTheme.typography.bodySmall, color = K.Muted)
        sameVendor.forEach { f -> ShelfLikeRow(f.displayName, f.color) { set(d.copyFrom(f)) } }
    }
}

@Composable
private fun ColorStep(d: FilamentDraft, errors: Map<String, String>, set: (FilamentDraft) -> Unit) {
    Box(Modifier.fillMaxWidth().padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
        SpoolDisc(d.colorHex.removePrefix("#").ifBlank { null }, 120.dp)
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        PALETTE.forEach { hex ->
            val sel = d.colorHex.removePrefix("#").equals(hex, true)
            Box(Modifier.size(44.dp).clip(CircleShape).background(io.github.xnovosx.kobraspoolman.ui.theme.spoolColor(hex))
                .border(if (sel) 3.dp else 1.dp, if (sel) K.Accent else K.LineStrong, CircleShape)
                .clickable(role = Role.RadioButton) { set(d.copy(colorHex = hex)) })
        }
    }
    TextInput("Farbe als Hex (RRGGBB), z.B. vom Hersteller", d.colorHex, { set(d.copy(colorHex = it.trim().removePrefix("#").take(6))) },
        error = errors["color"])
}

@Composable
private fun SummaryStep(d: FilamentDraft, specs: List<FieldSpec>, fields: List<io.github.xnovosx.kobraspoolman.data.ExtraField>,
                        template: String?, set: (FilamentDraft) -> Unit) {
    val own = specs.filter { d.value(it.key).isNotBlank() && it.key !in setOf("orca_overrides") }
    Text("Eigene Werte (${own.size})", style = MaterialTheme.typography.titleLarge)
    if (own.isEmpty()) Text("Keine – alles kommt aus ${template ?: "dem Orca-Profil"}.", color = K.Muted,
        style = MaterialTheme.typography.bodyMedium)
    own.forEach { s ->
        Row(Modifier.fillMaxWidth()) {
            Text(s.label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Text(d.value(s.key) + (s.unit?.let { " $it" } ?: ""), fontFamily = PlexMono, style = MaterialTheme.typography.bodyMedium)
        }
    }
    FilamentForm.spec("orca_overrides", fields)?.let { s ->
        SectionLabel("Orca-Overrides (optional)", Modifier.padding(top = 12.dp))
        Text("Weitere Orca-Einstellungen, eine je Zeile: schluessel = wert", style = MaterialTheme.typography.bodySmall,
            color = K.Muted)
        OutlinedTextField(d.value(s.key), { set(d.with(s.key, it)) }, modifier = Modifier.fillMaxWidth().heightIn(min = 110.dp),
            textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = PlexMono), shape = RoundedCornerShape(12.dp),
            placeholder = { Text("slow_down_layer_time = 8") })
    }
}

/** Ein Wert mit Platzhalter aus der Vorlage; eigener Wert wird gelb umrandet. */
@Composable
private fun FieldRow(s: FieldSpec, value: String, inherited: String?, error: String?, onChange: (String) -> Unit) {
    val own = value.isNotBlank()
    val shape = RoundedCornerShape(14.dp)
    Row(Modifier.fillMaxWidth().heightIn(min = 60.dp).clip(shape).background(K.Surface)
        .border(1.dp, if (error != null) K.DangerLine else if (own) K.Accent.copy(alpha = 0.55f) else K.Line, shape)
        .padding(horizontal = 14.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(s.label, style = MaterialTheme.typography.bodyMedium)
            Text(error ?: s.orcaKey ?: "", style = MaterialTheme.typography.bodySmall,
                color = if (error != null) K.DangerText else K.Muted)
        }
        if (s.kind == Kind.BOOL) {
            val inh = inherited?.let { if (it == "true") "an" else "aus" }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Pill("Vorlage" + (inh?.let { " ($it)" } ?: ""), value.isBlank(), small = true) { onChange("") }
                Pill("an", value == "true", small = true) { onChange("true") }
                Pill("aus", value == "false", small = true) { onChange("false") }
            }
        } else {
            OutlinedTextField(
                value = value, onValueChange = onChange, singleLine = true, modifier = Modifier.width(96.dp),
                textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = PlexMono, color = K.Accent, textAlign = TextAlign.End),
                placeholder = { Text(inherited ?: "–", fontFamily = PlexMono, color = K.Faint, textAlign = TextAlign.End,
                    modifier = Modifier.fillMaxWidth()) },
                keyboardOptions = KeyboardOptions(keyboardType = if (s.kind == Kind.TEXT) KeyboardType.Text else KeyboardType.Decimal),
                shape = RoundedCornerShape(10.dp),
                colors = OutlinedTextFieldDefaults.colors(unfocusedContainerColor = K.Ground, focusedContainerColor = K.Ground),
            )
            Text(s.unit.orEmpty(), style = MaterialTheme.typography.bodySmall, color = K.Muted,
                modifier = Modifier.width(44.dp).padding(start = 6.dp))
        }
    }
}

@Composable
private fun TextInput(label: String, value: String, onChange: (String) -> Unit, error: String? = null) {
    OutlinedTextField(value, onChange, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp), isError = error != null,
        supportingText = error?.let { { Text(it) } })
}

@Composable
private fun Pill(text: String, selected: Boolean, small: Boolean = false, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, modifier = Modifier.height(if (small) 36.dp else 44.dp), shape = RoundedCornerShape(22.dp),
        contentPadding = PaddingValues(horizontal = if (small) 10.dp else 16.dp),
        border = BorderStroke(if (selected) 2.dp else 1.dp, if (selected) K.Accent else K.LineStrong),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = if (selected) K.AccentSoft else K.Surface,
            contentColor = if (selected) K.Accent else K.Text),
    ) { Text(text, style = if (small) MaterialTheme.typography.labelSmall else MaterialTheme.typography.labelMedium) }
}

@Composable
private fun ShelfLikeRow(title: String, color: String, onClick: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Row(Modifier.fillMaxWidth().heightIn(min = 52.dp).clip(shape).background(K.Sunken).border(1.dp, K.Line, shape)
        .clickable(role = Role.Button, onClick = onClick).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        SpoolDisc(color, 28.dp)
        Text(title, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Text("übernehmen", style = MaterialTheme.typography.labelMedium, color = K.Accent)
    }
}
