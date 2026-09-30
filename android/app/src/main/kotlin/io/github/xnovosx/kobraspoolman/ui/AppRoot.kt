package io.github.xnovosx.kobraspoolman.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.xnovosx.kobraspoolman.BuildConfig
import io.github.xnovosx.kobraspoolman.data.SpoolInfo
import io.github.xnovosx.kobraspoolman.nfc.TagScanner
import io.github.xnovosx.kobraspoolman.ui.theme.K

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppRoot(vm: AppViewModel, scanner: TagScanner) {
    val connection by vm.connection.collectAsState()
    val state by vm.state.collectAsState()
    val error by vm.error.collectAsState()
    val busy by vm.busy.collectAsState()
    val catalog by vm.catalog.collectAsState()
    val detail by vm.detail.collectAsState()
    val nav = rememberNavController()
    val snackbar = remember { SnackbarHostState() }
    var scanOpen by remember { mutableStateOf(false) }
    var unknownTag by remember { mutableStateOf<String?>(null) }
    var linkTagUid by remember { mutableStateOf<String?>(null) }
    var fillSlot by remember { mutableStateOf<Int?>(null) }
    val route = nav.currentBackStackEntryAsState().value?.destination?.route
    val slotCount = state?.slots?.size?.takeIf { it > 0 } ?: 4
    val canWrite = state?.canWrite == true && connection?.token?.isNotBlank() == true

    // Android 17: Zugriff aufs Heimnetz (Bridge) braucht eine Berechtigung, sonst haengt jede Verbindung
    val context = LocalContext.current
    var lanGranted by remember { mutableStateOf(LocalNetwork.granted(context)) }
    val lanLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { lanGranted = it }
    LaunchedEffect(Unit) { if (!lanGranted) lanLauncher.launch(LocalNetwork.PERMISSION) }
    val askLan = { lanLauncher.launch(LocalNetwork.PERMISSION) }

    // Nur im Vordergrund die Bridge abfragen
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(connection) {
        if (connection?.configured != true) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            vm.startPolling()
            try { kotlinx.coroutines.awaitCancellation() } finally { vm.stopPolling() }
        }
    }
    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }
    LaunchedEffect(Unit) { scanner.tags.collect { vm.onTag(it) } }
    LaunchedEffect(Unit) {
        scanner.writes.collect { r ->
            vm.onTagWritten(r) { id -> nav.navigate("spool/$id") { popUpTo("slots") } }
        }
    }
    val tagJob by vm.tagJob.collectAsState()
    LaunchedEffect(Unit) {
        vm.scans.collect { r ->
            scanOpen = false
            when (r) {
                is ScanResult.Known -> nav.navigate("spool/${r.spoolId}") { launchSingleTop = true }
                is ScanResult.Unknown -> unknownTag = r.uid
            }
        }
    }
    val c = connection ?: return   // Einstellungen noch nicht geladen

    Scaffold(
        containerColor = K.Ground,
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            // Nur auf der Startseite; "Neue Spule" ist ein eigener Arbeitsschritt mit Abbrechen-Knopf
            if (route == "slots") BottomBar(
                current = route,
                onSlots = { nav.navigate("slots") { popUpTo("slots") { inclusive = false }; launchSingleTop = true } },
                onNew = { nav.navigate("new") { launchSingleTop = true } },
                onScan = { scanOpen = true },
            )
        },
    ) { padding ->
        NavHost(nav, startDestination = if (c.configured) "slots" else "settings") {
            composable("slots") {
                SlotsScreen(state, error.takeIf { lanGranted }, padding, lanMissing = !lanGranted, onGrantLan = askLan,
                    onRefresh = { vm.refreshNow() },
                    onSettings = { nav.navigate("settings") },
                    onSpool = { nav.navigate("spool/$it") },
                    onEmptySlot = { fillSlot = it })
            }
            composable("spool/{id}", arguments = listOf(navArgument("id") { type = NavType.IntType })) { entry ->
                val id = entry.arguments?.getInt("id") ?: return@composable
                LaunchedEffect(id, state) { vm.loadSpool(id) }
                SpoolScreen(detail?.takeIf { it.spool.spoolId == id }, slotCount, canWrite, busy, padding,
                    onBack = { nav.popBackStack() },
                    onMove = { vm.moveSpool(id, it) },
                    onArchive = { vm.archiveSpool(id) { nav.popBackStack() } },
                    onWriteTag = { nav.navigate("tag/$id") })
            }
            composable("new?uid={uid}", arguments = listOf(navArgument("uid") { nullable = true; defaultValue = null })) { entry ->
                val uid = entry.arguments?.getString("uid")
                val created by vm.createdFilament.collectAsState()
                NewSpoolScreen(catalog, slotCount, uid, canWrite, busy, padding, preselect = created,
                    onLoad = { vm.loadCatalog() },
                    onNewFilament = { nav.navigate("filament/new") },
                    onCancel = { nav.popBackStack() },
                    onCreate = { req ->
                        // Nach dem Anlegen gleich den Tag beschreiben ("Spaeter" fuehrt zur Spulenkarte)
                        vm.createSpool(req, uid) { sp ->
                            nav.navigate("tag/${sp.spoolId}") { popUpTo("slots") }
                        }
                    })
            }
            composable("tag/{id}", arguments = listOf(navArgument("id") { type = NavType.IntType })) { entry ->
                val id = entry.arguments?.getInt("id") ?: return@composable
                TagWriteScreen(id, tagJob?.takeIf { it.spoolId == id }, scanner, padding,
                    onPrepare = { vm.prepareTag(id, scanner) },
                    onCancel = {
                        vm.cancelTag(scanner)
                        nav.navigate("spool/$id") { popUpTo("slots") }
                    })
            }
            composable("filament/new") {
                FilamentScreen(catalog, canWrite, busy, padding,
                    onLoad = { vm.loadCatalog() },
                    onCancel = { nav.popBackStack() },
                    onCreate = { draft, specs -> vm.createFilament(draft, specs) { nav.popBackStack() } })
            }
            composable("settings") {
                SettingsScreen(c, busy, padding, lanMissing = !lanGranted, onGrantLan = askLan, canGoBack = c.configured, onBack = { nav.popBackStack() },
                    onSave = { newC ->
                        vm.saveConnection(newC) {
                            nav.navigate("slots") { popUpTo(0); launchSingleTop = true }
                        }
                    })
            }
        }
    }

    if (scanOpen) {
        ModalBottomSheet(onDismissRequest = { scanOpen = false }, containerColor = K.Surface) {
            ScanSheet(scanner, state?.let { allSpools(it.slots.mapNotNull { s -> s.spool } + it.shelf) }.orEmpty())
        }
    }
    unknownTag?.let { uid ->
        AlertDialog(
            onDismissRequest = { unknownTag = null },
            title = { Text("Unbekannter Tag") },
            text = { Text("Dieser Tag ($uid) gehört noch zu keiner Spule.") },
            confirmButton = {
                TextButton(onClick = { unknownTag = null; nav.navigate("new?uid=$uid") }) { Text("Neue Spule") }
            },
            dismissButton = {
                TextButton(onClick = { unknownTag = null; linkTagUid = uid }) { Text("Mit vorhandener verknüpfen") }
            },
            containerColor = K.Surface,
        )
    }
    linkTagUid?.let { uid ->
        SpoolPicker(
            title = "Tag verknüpfen mit …",
            spools = state?.let { allSpools(it.slots.mapNotNull { s -> s.spool } + it.shelf) }.orEmpty(),
            onDismiss = { linkTagUid = null },
            onPick = { sp -> linkTagUid = null; vm.linkTag(sp.spoolId, uid) { nav.navigate("spool/${sp.spoolId}") } },
        )
    }
    fillSlot?.let { slot ->
        SpoolPicker(
            title = "Spule für Slot $slot",
            spools = state?.shelf.orEmpty(),
            onDismiss = { fillSlot = null },
            onPick = { sp -> fillSlot = null; vm.moveSpool(sp.spoolId, slot) },
        )
    }
}

private fun allSpools(list: List<SpoolInfo>) = list.distinctBy { it.spoolId }

@Composable
private fun BottomBar(current: String?, onSlots: () -> Unit, onNew: () -> Unit, onScan: () -> Unit) {
    Box(Modifier.fillMaxWidth().background(K.Sunken).navigationBarsPadding()) {
        Row(Modifier.fillMaxWidth().height(72.dp), horizontalArrangement = Arrangement.SpaceAround,
            verticalAlignment = Alignment.CenterVertically) {
            NavItem(KIcons.Grid, "Slots", current == "slots", onSlots)
            Box(Modifier.size(64.dp))
            NavItem(KIcons.Plus, "Neu", current?.startsWith("new") == true, onNew)
        }
        Box(
            Modifier.align(Alignment.TopCenter).offset(y = (-22).dp).size(68.dp).clip(CircleShape).background(K.Accent)
                .border(4.dp, K.Ground, CircleShape).clickable(role = Role.Button, onClick = onScan),
            contentAlignment = Alignment.Center,
        ) { Icon(KIcons.Nfc, contentDescription = "Scannen", tint = K.OnAccent, modifier = Modifier.size(30.dp)) }
    }
}

@Composable
private fun NavItem(icon: ImageVector, label: String, selected: Boolean, onClick: () -> Unit) {
    Column(Modifier.clip(RoundedCornerShape(12.dp)).clickable(role = Role.Tab, onClick = onClick)
        .padding(horizontal = 16.dp, vertical = 6.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(icon, contentDescription = null, tint = if (selected) K.Accent else K.Muted, modifier = Modifier.size(24.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, color = if (selected) K.Accent else K.Muted)
    }
}

@Composable
private fun ScanSheet(scanner: TagScanner, spools: List<SpoolInfo>) {
    LazyColumn(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        item {
            Box(Modifier.size(120.dp).clip(CircleShape).background(K.AccentSoft).border(2.dp, K.Accent, CircleShape),
                contentAlignment = Alignment.Center) {
                Icon(KIcons.Nfc, contentDescription = null, tint = K.Accent, modifier = Modifier.size(52.dp))
            }
        }
        item { Text("Spule ans Handy halten", style = MaterialTheme.typography.titleLarge) }
        item {
            Text(when {
                !scanner.nfcAvailable -> "Dieses Gerät hat kein NFC."
                !scanner.nfcEnabled -> "NFC ist ausgeschaltet – in den Android-Einstellungen einschalten."
                else -> "Mitte der Handy-Rückseite auf den Tag der Spule."
            }, style = MaterialTheme.typography.bodyMedium, color = K.Muted)
        }
        if (BuildConfig.DEBUG) {
            item { SectionLabel("Virtuelle Tags (Test ohne NFC)", Modifier.fillMaxWidth().padding(top = 12.dp)) }
            item {
                TextButton(onClick = { scanner.simulate(TagScanner.randomUid()) }, modifier = Modifier.fillMaxWidth()) {
                    Text("Neuer, leerer Tag", color = K.Accent)
                }
            }
            items(spools.filter { it.nfcUid != null }, key = { it.spoolId }) { sp ->
                ShelfRow(sp) { scanner.simulate(sp.nfcUid!!) }
            }
        }
    }
}

@Composable
private fun SpoolPicker(title: String, spools: List<SpoolInfo>, onDismiss: () -> Unit, onPick: (SpoolInfo) -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            if (spools.isEmpty()) Text("Keine passende Spule.", color = K.Muted)
            else LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(spools, key = { it.spoolId }) { ShelfRow(it) { onPick(it) } }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Abbrechen") } },
        containerColor = K.Surface,
    )
}
