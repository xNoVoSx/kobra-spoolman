package io.github.xnovosx.kobraspoolman

import io.github.xnovosx.kobraspoolman.data.ExtraField
import io.github.xnovosx.kobraspoolman.data.FilamentDraft
import io.github.xnovosx.kobraspoolman.data.FilamentForm
import io.github.xnovosx.kobraspoolman.data.FilamentInfo
import io.github.xnovosx.kobraspoolman.data.Template
import io.github.xnovosx.kobraspoolman.data.placeholder
import io.github.xnovosx.kobraspoolman.data.templateFor
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FilamentDraftTest {
    private val fields = listOf(
        ExtraField("vorlage", "Vorlage", "choice"),
        ExtraField("orca_basis", "Orca-Basisprofil", "text"),
        ExtraField("nozzle_temp_first_layer", "Düse erste Schicht", "integer", "°C", orcaKey = "nozzle_temperature_initial_layer"),
        ExtraField("flow_ratio", "Flow Ratio", "float"),
        ExtraField("air_filtration", "Luftfilterung (Abluft)", "boolean"),
        ExtraField("orca_overrides", "Orca-Overrides", "text"),
        ExtraField("neues_feld", "Neu", "integer"),
    )
    private val petg = Template(10, "Vorlage PETG", "PETG",
        native = mapOf("settings_extruder_temp" to JsonPrimitive(255), "density" to JsonPrimitive(1.27)),
        extra = mapOf("nozzle_temp_first_layer" to JsonPrimitive(255)))
    private val specs = FilamentForm.all(fields)

    @Test fun only_entered_values_are_sent() {
        val d = FilamentDraft(vendorId = 2, name = "PETG 2.0 Mintgrün", material = "PETG", colorHex = "#3fa46a")
            .with("settings_extruder_temp", "250").with("flow_ratio", "0,95").with("air_filtration", "true")
            .with("nozzle_temp_first_layer", "")
        assertTrue(d.errors(specs).isEmpty())
        assertEquals("""{"name":"PETG 2.0 Mintgrün","material":"PETG","vendor_id":2,"color_hex":"3FA46A",""" +
            """"settings_extruder_temp":250,"extra":{"air_filtration":true,"flow_ratio":0.95}}""",
            d.toJson(specs, 2).toString())
    }

    @Test fun validation() {
        val e = FilamentDraft(colorHex = "lila").with("flow_ratio", "viel").errors(specs)
        assertEquals(setOf("name", "material", "vendor", "color", "flow_ratio"), e.keys)
    }

    @Test fun template_placeholders_follow_bridge_rules() {
        val d = FilamentDraft(material = "petg")
        val t = templateFor(d, listOf(petg))
        assertEquals("Vorlage PETG", t?.name)
        assertEquals("255", placeholder(t, FilamentForm.spec("settings_extruder_temp", fields)!!))
        assertEquals("1.27", placeholder(t, FilamentForm.spec("density", fields)!!))
        // eigenes Orca-Profil ersetzt die Vorlage komplett
        assertNull(templateFor(d.with("orca_basis", "Sunlu PETG @System"), listOf(petg)))
    }

    @Test fun copy_takes_the_product_lines_own_values_only() {
        val src = FilamentInfo(filamentId = 20, vendorId = 2, material = "PETG",
            native = mapOf("settings_extruder_temp" to JsonPrimitive(250), "name" to JsonPrimitive("Lavendel"),
                "color_hex" to JsonPrimitive("685BC7"), "weight" to JsonPrimitive(1000.0)),
            extra = mapOf("flow_ratio" to JsonPrimitive(0.95), "vorlage" to JsonPrimitive("Vorlage PETG")))
        val d = FilamentDraft(name = "PETG 2.0 Mintgrün").copyFrom(src)
        assertEquals(2, d.vendorId)
        assertEquals("PETG", d.material)
        assertEquals("250", d.value("settings_extruder_temp"))
        assertEquals("1000", d.value("weight"))
        assertEquals("0.95", d.value("flow_ratio"))
        assertEquals("Vorlage PETG", d.template)
        assertFalse("color_hex" in d.values || "name" in d.values)
    }

    @Test fun unknown_fields_of_a_newer_bridge_still_show_up() {
        assertEquals(listOf("neues_feld"), FilamentForm.others(fields).map { it.key })
    }
}
