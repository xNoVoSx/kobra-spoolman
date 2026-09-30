package io.github.xnovosx.kobraspoolman

import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.EncodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeWriter
import io.github.xnovosx.kobraspoolman.data.PairLink
import org.junit.Assert.assertEquals
import org.junit.Test

/** Der Kopplungs-QR-Code (wie in der App erzeugt) laesst sich mit ZXing wieder lesen. */
class PairQrTest {
    @Test fun generated_code_decodes_to_the_same_pair_link() {
        val link = PairLink("http://192.168.1.10:7913", "772182")
        val size = 360
        val m = QRCodeWriter().encode(link.toUri(), BarcodeFormat.QR_CODE, size, size, mapOf(EncodeHintType.MARGIN to 2))
        val px = IntArray(size * size) { i -> if (m[i % size, i / size]) 0xFF000000.toInt() else 0xFFFFFFFF.toInt() }
        val text = MultiFormatReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(size, size, px)))).text
        assertEquals(link, PairLink.parse(text))
    }
}
