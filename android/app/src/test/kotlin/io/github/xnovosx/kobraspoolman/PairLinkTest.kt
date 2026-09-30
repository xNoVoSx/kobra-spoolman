package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.PairLink
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PairLinkTest {
    @Test fun roundtrip() {
        val l = PairLink("http://192.168.1.10:7913", "042917")
        assertEquals(l, PairLink.parse(l.toUri()))
    }

    @Test fun rejects_foreign_or_broken_codes() {
        assertNull(PairLink.parse("https://example.com"))
        assertNull(PairLink.parse("kobraspoolman://pair?b=http%3A%2F%2Fx&c=12"))
        assertNull(PairLink.parse("kobraspoolman://pair?b=javascript%3Aalert(1)&c=123456"))
    }
}
