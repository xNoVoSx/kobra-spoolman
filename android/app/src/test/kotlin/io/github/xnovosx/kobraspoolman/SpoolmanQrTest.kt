package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.SpoolmanQr
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Spoolman label QR codes: both forms, spool and filament, anything else is not ours. */
class SpoolmanQrTest {
    @Test fun scheme_form() {
        assertEquals(SpoolmanQr.Spool(12), SpoolmanQr.parse("web+spoolman:s-12"))
        assertEquals(SpoolmanQr.Spool(7), SpoolmanQr.parse(" WEB+SPOOLMAN:S-7\n"))
        assertEquals(SpoolmanQr.Filament(3), SpoolmanQr.parse("web+spoolman:f-3"))
    }

    @Test fun http_form_with_any_host_and_base_path() {
        assertEquals(SpoolmanQr.Spool(12), SpoolmanQr.parse("http://spoolman.local:7912/spool/show/12"))
        assertEquals(SpoolmanQr.Spool(5), SpoolmanQr.parse("https://example.org/spoolman/spool/show/5/"))
        assertEquals(SpoolmanQr.Filament(9), SpoolmanQr.parse("http://spoolman.example:7912/filament/show/9?x=1"))
    }

    @Test fun other_codes_are_not_spoolman() {
        assertNull(SpoolmanQr.parse("kobra-spoolman://pair?url=http://x&code=1"))
        assertNull(SpoolmanQr.parse("web+spoolman:s-0"))
        assertNull(SpoolmanQr.parse("web+spoolman:x-4"))
        assertNull(SpoolmanQr.parse("http://shop.example/spool/12"))
        assertNull(SpoolmanQr.parse(""))
        assertNull(SpoolmanQr.parse(null))
    }
}
