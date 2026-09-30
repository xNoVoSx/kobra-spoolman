package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.BridgeClient
import io.github.xnovosx.kobraspoolman.data.BridgeException
import io.github.xnovosx.kobraspoolman.data.NewSpool
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class BridgeClientTest {
    private val server = MockWebServer()

    @Before fun start() = server.start()
    @After fun stop() = server.close()

    private fun client(token: String = "geheim") = BridgeClient(server.url("/").toString(), token)
    private fun reply(code: Int, body: String) = server.enqueue(MockResponse.Builder().code(code).body(body).build())

    @Test fun state_is_parsed_and_unknown_fields_ignored() = runTest {
        reply(200, """{"version":"2.4.0","neu":1,"printer":{"state":"printing","progress":0.42,"eta_s":1740,"active_slot":1},
            "can_write":true,"slots":[{"slot":1,"ace":{"present":true,"active":true,"material":"PETG","color":"685BC7","tag_id":0},
            "hints":[],"spool":{"spool_id":1,"display_name":"Sunlu PETG 2.0 Lavendelviolett","remaining_weight":972.6,"color":"685BC7"}}],
            "shelf":[],"warnings":[]}""")
        val st = client().state()
        assertEquals("printing", st.printer.state)
        assertEquals(1, st.printer.activeSlot)
        assertEquals(1, st.slots.single().spool!!.spoolId)
        val req = server.takeRequest()
        assertEquals("/api/app/state", req.url.encodedPath)
        assertEquals("Bearer geheim", req.headers["Authorization"])   // Geraet auch beim Lesen erkennbar
    }

    @Test fun writes_send_token_and_json() = runTest {
        reply(201, """{"spool":{"spool_id":9,"display_name":"x"}}""")
        val sp = client().createSpool(NewSpool(filamentId = 20, initialWeight = 1000.0, slot = 2))
        assertEquals(9, sp.spoolId)
        val req = server.takeRequest()
        assertEquals("Bearer geheim", req.headers["Authorization"])
        assertEquals("""{"filament_id":20,"initial_weight":1000.0,"slot":2}""", req.body!!.utf8())
    }

    @Test fun bridge_error_message_is_passed_on() = runTest {
        reply(409, """{"error":"Dieser Tag gehoert schon zu Spule #3"}""")
        try {
            client().linkTag(1, "04A1B2C3D4E5F6")
            fail("erwartet BridgeException")
        } catch (e: BridgeException) {
            assertEquals(409, e.status)
            assertEquals("Dieser Tag gehoert schon zu Spule #3", e.message)
        }
    }
}
