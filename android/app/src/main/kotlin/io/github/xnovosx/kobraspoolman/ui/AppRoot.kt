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
import io.github.xnovosx.kobraspoolman.data.tr

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppRoot(vm: AppViewModel, scanner: TagScanner) {
    val connection by vm.connection.collectAsState()
    val state by vm.state.collectAsState()
    val error by vm.error.collectAsState()
    val busy by vm.busy.collectAsState()
    val catalog by vm.catalog.collectAsState()
    val detail by vm.detail.collectAsState()
    val me by vm.me.collectAsState()
    val meChecked by vm.meChecked.collectAsState()
    val devices by vm.devices.collectAsState()
    val pairingCode by vm.pairingCode.collectAsState()
    val appSetup by vm.appSetup.collectAsState()
    val features by vm.features.collectAsState()
    val setupInfo by vm.setup.collectAsState()
    val nav = rememberNavController()
    val snackbar = remember { SnackbarHostState() }
    var scanOpen by remember { mutableStateOf(false) }
    var unknownTag by remember { mutableStateOf<String?>(null) }
    var blankTag by remember { mutableStateOf<String?>(null) }
    var writeFor by remember { mutableStateOf(false) }
    var linkTagUid by remember { mutableStateOf<String?>(null) }
    var fillSlot by remember { mutableStateOf<Int?>(null) }
    var dryerOpen by remember { mutableStateOf(false) }
    var tuneOpen by remember { mutableStateOf(false) }
    val route = nav.currentBackStackEntryAsState().value?.destination?.route
    val slotCount = state?.slots?.size?.takeIf { it > 0 } ?: 4
    val canWrite = state?.canWrite == true && connection?.token?.isNotBlank() == true

    // Android 17: access to the home network (bridge) needs a permission, else every connection hangs
    val context = LocalContext.current
    var lanGranted by remember { mutableStateOf(LocalNetwork.granted(context)) }
    val lanLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { lanGranted = it }
    LaunchedEffect(Unit) { if (!lanGranted) lanLauncher.launch(LocalNetwork.PERMISSION) }
    // notifications (print monitoring) need a permission from Android 13 - ask after the one for the home network
    fun notifyGranted() = context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED
    var notifyOk by remember { mutableStateOf(notifyGranted()) }
    val notifyLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { notifyOk = it; vm.ensureMonitor() }
    LaunchedEffect(lanGranted, connection?.configured) {
        if (connection?.configured != true || !lanGranted) return@LaunchedEffect
        if (context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED)
            notifyLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        else vm.ensureMonitor()
    }
    val askLan = { lanLauncher.launch(LocalNetwork.PERMISSION) }

    // query the bridge only in the foreground
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(connection) {
        if (connection?.configured != true) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            vm.startPolling()
            try { kotlinx.coroutines.awaitCancellation() } finally { vm.stopPolling() }
        }
    }
    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }
    // once per start check whether the bridge brings a newer app
    LaunchedEffect(connection?.configured) { if (connection?.configured == true) vm.checkUpdate() }
    val hasUpdate = vm.appUpdate.collectAsState().value != null
    LaunchedEffect(Unit) { scanner.tags.collect { vm.onTag(it) } }
    LaunchedEffect(Unit) {
        scanner.writes.collect { r ->
            vm.onTagWritten(r, scanner) { id -> nav.navigate("spool/$id") { popUpTo("slots") } }
        }
    }
    val tagJob by vm.tagJob.collectAsState()
    LaunchedEffect(Unit) {
        vm.scans.collect { r ->
            scanOpen = false
            when (r) {
                is ScanResult.Known -> nav.navigate("spool/${r.spoolId}") { launchSingleTop = true }
                is ScanResult.Unknown -> if (r.blank) blankTag = r.uid else unknownTag = r.uid
            }
        }
    }
    val c = connection ?: return   // settings not loaded yet
    // setup: an app paired before this version only gets the hint; a freshly paired one opens the setup
    LaunchedEffect(c.token) { vm.decideAppSetup() }
    LaunchedEffect(appSetup, c.configured) {
        if (appSetup == "pending" && c.configured && route != "setup") nav.navigate("setup") { launchSingleTop = true }
    }

    Scaffold(
        containerColor = K.Ground,
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            // on the main tabs; sub pages (spool, new spool, ...) have their own back buttons
            if (route in TABS) BottomBar(
                current = route,
                notices = state?.notices?.messages.orEmpty().let { m -> m.size to (m.firstOrNull()?.level) },
                hasUpdate = hasUpdate,
                onTab = { t -> nav.navigate(t) { popUpTo("slots") { inclusive = false }; launchSingleTop = true } },
                onScan = { scanOpen = true },
            )
        },
    ) { padding ->
        NavHost(nav, startDestination = if (c.configured) "slots" else "settings") {
            composable("slots") {
                SlotsScreen(state, error.takeIf { lanGranted }, padding, lanMissing = !lanGranted, onGrantLan = askLan,
                    onRefresh = { vm.refreshNow() },
                    onSpool = { nav.navigate("spool/$it") },
                    onEmptySlot = { fillSlot = it },
                    onDryer = { dryerOpen = true },
                    onResume = { vm.resume(it) },
                    fetchImage = { vm.image(it) },
                    printInfo = { vm.printInfo() },
                    camera = { vm.cameraStream() },
                    viewerUrl = vm.viewerUrl(vm.connection.collectAsState().value, vm.render3d.collectAsState().value),
                    onPrintAction = { action, done -> vm.printAction(action, done) },
                    onTune = { tuneOpen = true },
                    onDirectOff = { vm.direct(false) })
            }
            composable("notices") { NoticesScreen(state, padding, onRefresh = { vm.refreshNow() }) }
            composable("filament") {
                FilamentHubScreen(state, catalog, padding,
                    onLoadCatalog = { vm.loadCatalog() },
                    onSpool = { nav.navigate("spool/$it") },
                    onNewSpool = { nav.navigate("new") { launchSingleTop = true } },
                    onNewFilament = { nav.navigate("filament/new") })
            }
            composable("more") {
                val update by vm.appUpdate.collectAsState()
                val progress by vm.updateProgress.collectAsState()
                MoreScreen(padding, update, progress, onInstall = { vm.installUpdate() }, onCheckUpdate = { vm.checkUpdate(true) },
                    hasAce = state?.dryer?.present == true,
                    onAce = { dryerOpen = true },
                    onJobs = { nav.navigate("jobs") },
                    onProtocol = { nav.navigate("protocol") },
                    onAi = { nav.navigate("ai") },
                    onDevices = { nav.navigate("devices") },
                    onFeatures = { nav.navigate("features") },
                    onSettings = { nav.navigate("settings") })
            }
            composable("features") {
                FeaturesScreen(padding, features, canWrite, busy,
                    onLoad = { vm.loadFeatures() },
                    onSwitch = { k, on -> vm.switchFeature(k, on) },
                    onSetup = { nav.navigate("setup") },
                    onBack = { nav.popBackStack() })
            }
            composable("setup") {
                val monitorOn by vm.monitor.collectAsState()
                SetupScreen(padding, setupInfo,
                    PhoneChecks(nfc = if (!scanner.nfcAvailable) null else scanner.nfcEnabled, notifications = notifyOk, monitor = monitorOn),
                    busy,
                    onLoad = { vm.loadSetup() },
                    onAllowNotifications = { notifyLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS) },
                    onMonitor = { vm.setMonitor(it) },
                    onApply = { choice, done -> vm.applySetup(choice, done) },
                    onFinish = { vm.finishSetup { nav.navigate("slots") { popUpTo(0); launchSingleTop = true } } })
            }
            composable("ai") { AiScreen(padding, vm, onBack = { nav.popBackStack() }) }
            composable("jobs") { JobsScreen(padding, load = { vm.jobs() }, onBack = { nav.popBackStack() }) }
            composable("protocol") {
                ProtocolScreen(padding, console = { vm.console(it) }, logs = { a, l -> vm.logs(a, l) },
                    onBack = { nav.popBackStack() })
            }
            composable("spool/{id}", arguments = listOf(navArgument("id") { type = NavType.IntType })) { entry ->
                val id = entry.arguments?.getInt("id") ?: return@composable
                LaunchedEffect(id, state) { vm.loadSpool(id) }
                SpoolScreen(detail?.takeIf { it.spool.spoolId == id }, slotCount, canWrite, busy, padding,
                    onBack = { nav.popBackStack() },
                    onMove = { vm.moveSpool(id, it) },
                    onArchive = { vm.archiveSpool(id) { nav.popBackStack() } },
                    onWriteTag = { side -> nav.navigate("tag/$id?side=$side") },
                    moisture = { SpoolMoistureSection(id, canWrite, { vm.spoolMoisture(it) }) { t, h, done -> vm.spoolDried(id, t, h, done) } })
            }
            composable("new?uid={uid}", arguments = listOf(navArgument("uid") { nullable = true; defaultValue = null })) { entry ->
                val uid = entry.arguments?.getString("uid")
                val created by vm.createdFilament.collectAsState()
                NewSpoolScreen(catalog, slotCount, uid, canWrite, busy, padding, preselect = created,
                    onLoad = { vm.loadCatalog() },
                    onNewFilament = { nav.navigate("filament/new") },
                    onCancel = { nav.popBackStack() },
                    onCreate = { req ->
                        // after creating, write the tag right away ("Later" leads to the spool card)
                        vm.createSpool(req, uid) { sp ->
                            nav.navigate("tag/${sp.spoolId}") { popUpTo("slots") }
                        }
                    })
            }
            composable("tag/{id}?side={side}", arguments = listOf(navArgument("id") { type = NavType.IntType },
                navArgument("side") { type = NavType.IntType; defaultValue = 1 })) { entry ->
                val id = entry.arguments?.getInt("id") ?: return@composable
                val side = entry.arguments?.getInt("side") ?: 1
                TagWriteScreen(id, tagJob?.takeIf { it.spoolId == id }, scanner, padding,
                    onPrepare = { vm.prepareTag(id, scanner, side) },
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
                val monitorOn by vm.monitor.collectAsState()
                SettingsScreen(c, me, meChecked, busy, padding, lanMissing = !lanGranted, onGrantLan = askLan,
                    monitor = monitorOn, onMonitor = { vm.setMonitor(it) },
                    render3d = vm.render3d.collectAsState().value, onRender3d = { vm.setRender3d(it) },
                    canGoBack = c.configured, onBack = { nav.popBackStack() },
                    onLoadMe = { vm.loadMe() },
                    onPair = { url, code, name ->
                        vm.pair(url, code, name) { nav.navigate("setup") { popUpTo(0); launchSingleTop = true } }
                    },
                    onForget = { vm.forgetPairing() },
                    onDevices = { nav.navigate("devices") })
            }
            composable("devices") {
                DevicesScreen(c.url, devices, pairingCode, busy, padding,
                    onLoad = { vm.loadDevices() },
                    onBack = { vm.clearPairingCode(); nav.popBackStack() },
                    onNewCode = { vm.newPairingCode() },
                    onCloseCode = { vm.clearPairingCode(); vm.loadDevices() },
                    onRemove = { vm.removeDevice(it.id) })
            }
        }
    }

    if (appSetup == "hint" && route in TABS) {
        FeaturesHintDialog(
            onLook = { vm.setAppSetup("seen"); nav.navigate("features") },
            onDismiss = { vm.setAppSetup("seen") })
    }

    val dryer = state?.dryer
    if (dryerOpen && dryer != null) {
        ModalBottomSheet(onDismissRequest = { dryerOpen = false }, containerColor = K.Surface) {
            DryerSheet(dryer, state?.ace,
                onStart = { t, h -> dryerOpen = false; vm.dryerStart(t, h) },
                onStop = { dryerOpen = false; vm.dryerStop() },
                onSaveConfig = { c -> dryerOpen = false; vm.dryerConfig(c) },
                onPlan = { at, t, h -> dryerOpen = false; vm.dryerSchedule(at, t, h) },
                onClearPlan = { vm.clearDryerSchedule() },
                onOption = { k, v, c -> vm.setAceOption(k, v, c) },
                purgePreview = { m -> vm.acePurge(m) },
                humidity = { HumiditySection({ h -> vm.humidity(h) }, if (canWrite) { id, done -> vm.discardDrying(id, done) } else null) },
                pa = {
                    state?.pa?.let { p ->
                        PaSection(p, state?.printer?.state in setOf("printing", "paused"), rinkhals = state?.ace?.variant == "rinkhals",
                            onSwitch = { e, a -> vm.paSwitch(e, a) }, onCalibrate = { vm.paCalibrate(it) },
                            onForget = { vm.paForget(it) })
                    }
                    state?.resume?.let { r -> PowerlossSwitch(r) { vm.resumeSwitch(it) } }
                    state?.clog?.let { c -> ClogSwitch(c, { vm.clogSwitch(enabled = it) }, { vm.clogSwitch(action = it) }) }
                    state?.let { st -> st.direct?.let { d -> st to d } }?.let { (st, d) ->
                        DirectSection(d, allSpools(st.slots.mapNotNull { s -> s.spool } + st.shelf),
                            aceLoadedSlot = st.slots.firstOrNull { s -> s.ace.active }?.slot,
                            printing = st.printer.state in setOf("printing", "paused"), canWrite = st.canWrite) { on, id, unload ->
                            dryerOpen = false; vm.direct(on, id, unload)
                        }
                    }
                    state?.usb?.let { u -> UsbSection(u) { key, v -> vm.setSwitch(key, v) } }
                })
        }
    }
    val printer = state?.printer
    if (tuneOpen && printer != null) {
        ModalBottomSheet(onDismissRequest = { tuneOpen = false }, containerColor = K.Surface) {
            TuneSheet(printer) { body -> tuneOpen = false; vm.tune(body) }
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
            title = { Text(tr("Unknown tag")) },
            text = { Text(tr("This tag ({uid}) is written but belongs to no spool yet – e.g. an original Anycubic tag.", "uid" to uid)) },
            confirmButton = {
                TextButton(onClick = { unknownTag = null; nav.navigate("new?uid=$uid") }) { Text(tr("New spool")) }
            },
            dismissButton = {
                TextButton(onClick = { unknownTag = null; linkTagUid = uid }) { Text(tr("Link with an existing one")) }
            },
            containerColor = K.Surface,
        )
    }
    // Empty sticker: don't link it (it would stay empty, the ACE could not read it) but write it - for a new or an
    // existing spool; afterwards the app asks for the second sticker (other side).
    blankTag?.let { uid ->
        AlertDialog(
            onDismissRequest = { blankTag = null },
            title = { Text(tr("Empty sticker")) },
            text = { Text(tr("This sticker is still empty. Which spool should it be written for? The second sticker for the other spool side follows right after.")) },
            confirmButton = {
                TextButton(onClick = { blankTag = null; writeFor = true }) { Text(tr("Existing spool")) }
            },
            dismissButton = {
                TextButton(onClick = { blankTag = null; nav.navigate("new") }) { Text(tr("New spool")) }
            },
            containerColor = K.Surface,
        )
    }
    if (writeFor) {
        SpoolPicker(
            title = tr("Write sticker for …"),
            spools = state?.let { allSpools(it.slots.mapNotNull { s -> s.spool } + it.shelf) }.orEmpty(),
            onDismiss = { writeFor = false },
            onPick = { sp ->
                writeFor = false
                // if the spool already has a tag, this sticker is the second one
                val side = if (sp.nfcUids.size == 1 || (sp.nfcUids.isEmpty() && sp.nfcUid != null)) 2 else 1
                nav.navigate("tag/${sp.spoolId}?side=$side")
            },
        )
    }
    linkTagUid?.let { uid ->
        SpoolPicker(
            title = tr("Link tag with …"),
            spools = state?.let { allSpools(it.slots.mapNotNull { s -> s.spool } + it.shelf) }.orEmpty(),
            onDismiss = { linkTagUid = null },
            onPick = { sp -> linkTagUid = null; vm.linkTag(sp.spoolId, uid) { nav.navigate("spool/${sp.spoolId}") } },
        )
    }
    fillSlot?.let { slot ->
        SpoolPicker(
            title = tr("Spool for slot {slot}", "slot" to slot),
            spools = state?.shelf.orEmpty(),
            onDismiss = { fillSlot = null },
            onPick = { sp -> fillSlot = null; vm.moveSpool(sp.spoolId, slot) },
        )
    }
}

private fun allSpools(list: List<SpoolInfo>) = list.distinctBy { it.spoolId }

private val TABS = setOf("slots", "notices", "filament", "more")

/** Home · messages (counter: red on errors, yellow on warnings) · NFC · filament · more */
@Composable
private fun BottomBar(current: String?, notices: Pair<Int, String?>, hasUpdate: Boolean, onTab: (String) -> Unit, onScan: () -> Unit) {
    Box(Modifier.fillMaxWidth().background(K.Sunken).navigationBarsPadding()) {
        Row(Modifier.fillMaxWidth().height(72.dp), horizontalArrangement = Arrangement.SpaceAround,
            verticalAlignment = Alignment.CenterVertically) {
            NavItem(KIcons.Grid, tr("Home"), current == "slots") { onTab("slots") }
            Box {
                NavItem(KIcons.Bell, tr("Messages"), current == "notices") { onTab("notices") }
                val (n, level) = notices
                if (n > 0 && level != "info") Text("$n", style = MaterialTheme.typography.labelSmall,
                    color = K.OnAccent, modifier = Modifier.align(Alignment.TopEnd).padding(end = 10.dp)
                        .clip(CircleShape).background(if (level == "error") K.Danger else K.Accent).padding(horizontal = 6.dp))
            }
            Box(Modifier.size(64.dp))
            NavItem(KIcons.Spool, tr("Filament"), current == "filament") { onTab("filament") }
            Box {
                NavItem(KIcons.More, tr("More"), current == "more") { onTab("more") }
                if (hasUpdate) Box(Modifier.align(Alignment.TopEnd).padding(top = 6.dp, end = 14.dp).size(9.dp)
                    .clip(CircleShape).background(K.Accent))
            }
        }
        Box(
            Modifier.align(Alignment.TopCenter).offset(y = (-22).dp).size(68.dp).clip(CircleShape).background(K.Accent)
                .border(4.dp, K.Ground, CircleShape).clickable(role = Role.Button, onClick = onScan),
            contentAlignment = Alignment.Center,
        ) { Icon(KIcons.Nfc, contentDescription = tr("Scan"), tint = K.OnAccent, modifier = Modifier.size(30.dp)) }
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
        item { Text(tr("Hold the spool to the phone"), style = MaterialTheme.typography.titleLarge) }
        item {
            Text(when {
                !scanner.nfcAvailable -> tr("This device has no NFC.")
                !scanner.nfcEnabled -> tr("NFC is switched off – switch it on in the Android settings.")
                else -> tr("Centre of the phone's back onto the spool's tag.")
            }, style = MaterialTheme.typography.bodyMedium, color = K.Muted)
        }
        if (BuildConfig.DEBUG) {
            item { SectionLabel(tr("Virtual tags (test without NFC)"), Modifier.fillMaxWidth().padding(top = 12.dp)) }
            item {
                TextButton(onClick = { scanner.simulate(TagScanner.randomUid()) }, modifier = Modifier.fillMaxWidth()) {
                    Text(tr("New, empty tag"), color = K.Accent)
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
            if (spools.isEmpty()) Text(tr("No matching spool."), color = K.Muted)
            else LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(spools, key = { it.spoolId }) { ShelfRow(it) { onPick(it) } }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(tr("Cancel")) } },
        containerColor = K.Surface,
    )
}
