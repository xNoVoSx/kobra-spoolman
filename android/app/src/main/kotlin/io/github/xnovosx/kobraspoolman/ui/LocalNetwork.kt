package io.github.xnovosx.kobraspoolman.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

/** Permission for the home network (Android 17+, "Nearby devices"). Older Android versions don't need it. */
object LocalNetwork {
    const val PERMISSION = Manifest.permission.ACCESS_LOCAL_NETWORK

    fun granted(context: Context): Boolean =
        Build.VERSION.SDK_INT < 37 || context.checkSelfPermission(PERMISSION) == PackageManager.PERMISSION_GRANTED
}
