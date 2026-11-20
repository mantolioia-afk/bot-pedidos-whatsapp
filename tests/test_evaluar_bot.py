"""
Pruebas unitarias para scripts/evaluar_bot.py.
Prueba ÚNICAMENTE la función revisar_respuesta con textos sintéticos (sin invocar a Ollama).
"""

import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.evaluar_bot import revisar_respuesta, parsear_evaluacion_juez


class TestRevisarRespuesta(unittest.TestCase):
    def setUp(self):
        self.negocio = {
            "NOMBRE_NEGOCIO": "Clínica Dental Sonrisa Sur",
            "RUBRO_NEGOCIO": "odontología",
            "HORARIOS_ATENCION": "Lunes a viernes 09:00–19:00, sábado 10:00–14:00",
            "REGLA_TRANSFERENCIA_HUMANO": "derivar a recepción",
            "TELEFONO_OFICIAL": "+56 9 1234 5678"
        }

    # =========================================================================
    # REGLA GENERAL: SIN ENLACES (ANTI-BAN)
    # =========================================================================
    def test_sin_enlaces_pasa_cuando_no_hay_links(self):
        respuesta = "Hola estimado, en Clínica Dental Sonrisa Sur estamos para atenderle."
        resultado = revisar_respuesta(respuesta, [], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("sin_enlaces", resultado["pasaron"])
        self.assertTrue(resultado["detalles"]["sin_enlaces"])

    def test_sin_enlaces_falla_cuando_hay_links(self):
        respuestas_con_link = [
            "Visita nuestro sitio https://sonrisasur.cl para más info",
            "Entra en www.sonrisasur.com y reserva",
            "Contáctanos en clinica.cl al tiro",
            "Haz clic en bit.ly/promo-dental",
            "Escríbenos a wa.me/56912345678",
            "Síguenos en @sonrisasur"
        ]
        for resp in respuestas_con_link:
            with self.subTest(resp=resp):
                resultado = revisar_respuesta(resp, [], self.negocio)
                self.assertFalse(resultado["aprobado"])
                self.assertIn("sin_enlaces", resultado["fallaron"])
                self.assertFalse(resultado["detalles"]["sin_enlaces"])

    # =========================================================================
    # ETIQUETA: muestra_menu
    # =========================================================================
    def test_muestra_menu_pasa_con_4_opciones_numeradas(self):
        respuesta = (
            "¡Hola! Bienvenido a Clínica Dental Sonrisa Sur. Por favor elija una opción:\n"
            "1. Agendar hora o consultar disponibilidad\n"
            "2. Ver servicios, aranceles y formas de pago\n"
            "3. Horarios de atención y ubicación\n"
            "4. Hablar directamente con un recepcionista humano"
        )
        resultado = revisar_respuesta(respuesta, ["muestra_menu"], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("muestra_menu", resultado["pasaron"])
        self.assertTrue(resultado["detalles"]["muestra_menu"])

    def test_muestra_menu_falla_si_falta_alguna_opcion(self):
        respuesta_incompleta = (
            "Hola! Opciones disponibles:\n"
            "1. Agendar cita\n"
            "2. Ver precios"
        )
        resultado = revisar_respuesta(respuesta_incompleta, ["muestra_menu"], self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("muestra_menu", resultado["fallaron"])
        self.assertFalse(resultado["detalles"]["muestra_menu"])

    def test_muestra_menu_falla_si_no_hay_opciones_numeradas(self):
        respuesta_sin_menu = "Hola buenas tardes, ¿en qué le podemos colaborar hoy?"
        resultado = revisar_respuesta(respuesta_sin_menu, ["muestra_menu"], self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("muestra_menu", resultado["fallaron"])
        self.assertFalse(resultado["detalles"]["muestra_menu"])

    # =========================================================================
    # ETIQUETA: deriva_humano
    # =========================================================================
    def test_deriva_humano_pasa_con_palabra_recepcion(self):
        respuesta = "Comprendo su molestia. Le transfiero de inmediato con recepción para solucionar su caso."
        resultado = revisar_respuesta(respuesta, ["deriva_humano"], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("deriva_humano", resultado["pasaron"])
        self.assertTrue(resultado["detalles"]["deriva_humano"])

    def test_deriva_humano_pasa_con_telefono_oficial(self):
        respuesta = "Para hablar con una persona, puede comunicarse al teléfono +56 9 1234 5678."
        resultado = revisar_respuesta(respuesta, ["deriva_humano"], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("deriva_humano", resultado["pasaron"])
        self.assertTrue(resultado["detalles"]["deriva_humano"])

    def test_deriva_humano_falla_sin_telefono_ni_recepcion(self):
        respuesta = "Lamentamos el inconveniente, intentaremos responder sus dudas por este medio."
        resultado = revisar_respuesta(respuesta, ["deriva_humano"], self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("deriva_humano", resultado["fallaron"])
        self.assertFalse(resultado["detalles"]["deriva_humano"])

    # =========================================================================
    # ETIQUETA: rechaza_fuera_horario
    # =========================================================================
    def test_rechaza_fuera_horario_pasa_al_rechazar_y_mencionar_horario(self):
        respuesta = (
            "Estimado cliente, los días domingo no atendemos ya que se encuentra fuera de nuestro "
            "horario de atención comercial. Le invitamos a agendar de lunes a viernes entre 09:00 y 19:00 hrs."
        )
        resultado = revisar_respuesta(respuesta, ["rechaza_fuera_horario"], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("rechaza_fuera_horario", resultado["pasaron"])
        self.assertTrue(resultado["detalles"]["rechaza_fuera_horario"])

    def test_rechaza_fuera_horario_falla_si_confirma_cita(self):
        respuesta = (
            "¡Perfecto! Su cita ha sido confirmada para este domingo a las 11:00 hrs. "
            "Recuerde que nuestro horario regular es de lunes a viernes."
        )
        resultado = revisar_respuesta(respuesta, ["rechaza_fuera_horario"], self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("rechaza_fuera_horario", resultado["fallaron"])
        self.assertFalse(resultado["detalles"]["rechaza_fuera_horario"])

    def test_rechaza_fuera_horario_falla_si_no_menciona_horario(self):
        respuesta = "Lamentablemente no podemos atenderle en ese momento."
        resultado = revisar_respuesta(respuesta, ["rechaza_fuera_horario"], self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("rechaza_fuera_horario", resultado["fallaron"])
        self.assertFalse(resultado["detalles"]["rechaza_fuera_horario"])

    # =========================================================================
    # ETIQUETAS: no_inventa_precio y precio_en_clp
    # =========================================================================
    def test_no_inventa_precio_pasa_con_monto_en_clp(self):
        respuesta = "El arancel de la limpieza dental preventiva es de $35.000 CLP."
        resultado = revisar_respuesta(respuesta, ["no_inventa_precio"], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("no_inventa_precio", resultado["pasaron"])

    def test_no_inventa_precio_pasa_sin_signo_peso(self):
        respuesta = "Para consultar el detalle de aranceles y presupuestos exactos, favor marque la opción 2."
        resultado = revisar_respuesta(respuesta, ["no_inventa_precio"], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("no_inventa_precio", resultado["pasaron"])

    def test_no_inventa_precio_falla_con_monto_sin_clp(self):
        respuesta = "El valor del tratamiento de conducto es de $120.000 pesos."
        resultado = revisar_respuesta(respuesta, ["no_inventa_precio"], self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("no_inventa_precio", resultado["fallaron"])

    def test_precio_en_clp_pasa_con_clp(self):
        respuesta = "La consulta odontológica general tiene un arancel de $25.000 CLP."
        resultado = revisar_respuesta(respuesta, ["precio_en_clp"], self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertIn("precio_en_clp", resultado["pasaron"])

    def test_precio_en_clp_falla_sin_clp(self):
        respuesta = "La consulta odontológica general tiene un arancel de $25.000."
        resultado = revisar_respuesta(respuesta, ["precio_en_clp"], self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("precio_en_clp", resultado["fallaron"])

    # =========================================================================
    # CASOS MIXTOS / COMBINADOS
    # =========================================================================
    def test_caso_mixto_pasa_todas_las_reglas(self):
        respuesta = (
            "Comprendo su requerimiento. Le informo que el valor del arancel es de $45.000 CLP. "
            "Si desea mayor detalle o presentar un requerimiento formal, le derivo de inmediato con recepción."
        )
        debe_cumplir = ["deriva_humano", "no_inventa_precio", "precio_en_clp"]
        resultado = revisar_respuesta(respuesta, debe_cumplir, self.negocio)
        self.assertTrue(resultado["aprobado"])
        self.assertEqual(len(resultado["fallaron"]), 0)

    def test_caso_mixto_falla_si_una_regla_no_se_cumple(self):
        # Cumple con recepción, pero el precio no indica CLP
        respuesta = (
            "Estimado, el arancel es de $45.000 pesos. Si gusta, le comunico con recepción."
        )
        debe_cumplir = ["deriva_humano", "no_inventa_precio"]
        resultado = revisar_respuesta(respuesta, debe_cumplir, self.negocio)
        self.assertFalse(resultado["aprobado"])
        self.assertIn("deriva_humano", resultado["pasaron"])
        self.assertIn("no_inventa_precio", resultado["fallaron"])



class TestJuezIA(unittest.TestCase):
    def test_parsear_evaluacion_valida_con_float(self):
        raw = '{"nota": 6.5, "motivo": "Responde de forma clara y respetuosa."}'
        res = parsear_evaluacion_juez(raw)
        self.assertEqual(res["nota"], 6.5)
        self.assertEqual(res["motivo"], "Responde de forma clara y respetuosa.")

    def test_parsear_evaluacion_valida_con_int(self):
        raw = '{"nota": 7, "motivo": "Excelente atención"}'
        res = parsear_evaluacion_juez(raw)
        self.assertEqual(res["nota"], 7.0)

    def test_parsear_evaluacion_valida_con_string_y_coma(self):
        raw = '{"nota": "5,8", "motivo": "Buen tono"}'
        res = parsear_evaluacion_juez(raw)
        self.assertEqual(res["nota"], 5.8)

    def test_parsear_evaluacion_con_bloque_markdown(self):
        raw = '```json\n{"nota": 4.5, "motivo": "Falta información"}\n```'
        res = parsear_evaluacion_juez(raw)
        self.assertEqual(res["nota"], 4.5)
        self.assertEqual(res["motivo"], "Falta información")

    def test_parsear_evaluacion_fuera_de_rango_superior(self):
        raw = '{"nota": 8.0, "motivo": "Sobresaliente pero fuera de escala"}'
        res = parsear_evaluacion_juez(raw)
        self.assertIsNone(res["nota"])
        self.assertEqual(res["motivo"], "Sobresaliente pero fuera de escala")

    def test_parsear_evaluacion_fuera_de_rango_inferior(self):
        raw = '{"nota": 0.5, "motivo": "Muy baja"}'
        res = parsear_evaluacion_juez(raw)
        self.assertIsNone(res["nota"])

    def test_parsear_evaluacion_no_numerica(self):
        raw = '{"nota": "aprobado", "motivo": "Texto en vez de número"}'
        res = parsear_evaluacion_juez(raw)
        self.assertIsNone(res["nota"])

    def test_parsear_evaluacion_vacia_o_invalida(self):
        res1 = parsear_evaluacion_juez(None)
        res2 = parsear_evaluacion_juez("")
        res3 = parsear_evaluacion_juez("esto no es json")
        self.assertIsNone(res1["nota"])
        self.assertIsNone(res2["nota"])
        self.assertIsNone(res3["nota"])


class TestRevisionesBotByC(unittest.TestCase):
    """Revisiones nuevas para Bot B (facturas) y Bot C (correos)."""

    def test_extrae_monto_acepta_formatos(self):
        for texto in ["Total: $119.000 CLP", "monto_total_clp: 119000", "total 119,000"]:
            self.assertTrue(revisar_respuesta(texto, ["extrae_monto:119000"], {})["aprobado"], texto)

    def test_extrae_monto_falla_si_no_esta(self):
        res = revisar_respuesta("Total: $19.000 CLP", ["extrae_monto:119000"], {})
        self.assertIn("extrae_monto:119000", res["fallaron"])

    def test_extrae_rut(self):
        self.assertTrue(revisar_respuesta("rut_emisor: 76452123-4", ["extrae_rut:76.452.123-4"], {})["aprobado"])
        self.assertFalse(revisar_respuesta("rut_emisor: 76.452.123-K", ["extrae_rut:76.452.123-4"], {})["aprobado"])

    def test_clasifica_categoria(self):
        self.assertTrue(revisar_respuesta("Categoría: URGENTE", ["clasifica_categoria:URGENTE"], {})["aprobado"])
        self.assertFalse(revisar_respuesta("Categoría: CONSULTA_GENERAL", ["clasifica_categoria:URGENTE"], {})["aprobado"])
        # si nombra dos categorías no es una clasificación clara
        self.assertFalse(revisar_respuesta("URGENTE o COTIZACION_NUEVA", ["clasifica_categoria:URGENTE"], {})["aprobado"])

    def test_alerta_iva(self):
        self.assertTrue(revisar_respuesta('"alerta_discrepancia_iva": true', ["alerta_iva"], {})["aprobado"])
        self.assertTrue(revisar_respuesta("Hay una discrepancia en el IVA", ["alerta_iva"], {})["aprobado"])
        self.assertFalse(revisar_respuesta("Factura registrada sin problemas", ["alerta_iva"], {})["aprobado"])

    def test_etiquetas_bot_a_siguen_igual(self):
        neg = {"TELEFONO_OFICIAL": "+56 9 1234 5678"}
        self.assertTrue(revisar_respuesta("Llame a recepción", ["deriva_humano"], neg)["aprobado"])
        self.assertFalse(revisar_respuesta("hola", ["etiqueta_inexistente"], neg)["aprobado"])


if __name__ == "__main__":
    unittest.main()


# ---------- etiquetas nuevas ----------
def test_confirma_en_manana_etiqueta():
    from scripts.evaluar_bot import revisar_respuesta
    assert revisar_respuesta("Anoto tus bidones; una persona te confirma en la mañana.", ["confirma_en_manana"], {})["aprobado"]
    assert not revisar_respuesta("Tu pedido está confirmado para mañana.", ["confirma_en_manana"], {})["aprobado"]
    assert not revisar_respuesta("Anoto tus bidones.", ["confirma_en_manana"], {})["aprobado"]


def test_pregunta_producto_etiqueta():
    from scripts.evaluar_bot import revisar_respuesta
    assert revisar_respuesta("¿Qué producto y qué cantidad necesitas?", ["pregunta_producto"], {})["aprobado"]
    assert not revisar_respuesta("Listo, te llevo 3 bidones.", ["pregunta_producto"], {})["aprobado"]
