package io.github.xnovosx.kobraspoolman.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Secrets on the phone (the Home Assistant token - it can do whatever its HA user may): AES-GCM with a key in the
 * Android Keystore, which never leaves it. Stored is base64(IV + ciphertext).
 */
object Secrets {
    private const val ALIAS = "kobra_remote"
    private const val GCM = "AES/GCM/NoPadding"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build())
        }.generateKey()
    }

    fun seal(plain: String): String {
        if (plain.isEmpty()) return ""
        val c = Cipher.getInstance(GCM).apply { init(Cipher.ENCRYPT_MODE, key()) }
        return Base64.encodeToString(c.iv + c.doFinal(plain.toByteArray()), Base64.NO_WRAP)
    }

    /** "" when there is nothing or it cannot be read any more (key gone, e.g. app data moved) - then enter it again. */
    fun open(sealed: String): String {
        if (sealed.isEmpty()) return ""
        return runCatching {
            val raw = Base64.decode(sealed, Base64.NO_WRAP)
            val c = Cipher.getInstance(GCM).apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw, 0, 12)) }
            String(c.doFinal(raw, 12, raw.size - 12))
        }.getOrDefault("")
    }
}
