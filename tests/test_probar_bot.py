"""Pruebas para scripts/probar_bot.py (chat local sin WhatsApp ni Meta)."""
import json
import os
from unittest import mock

import pytest

from scripts import probar_bot as pb
from src.whatsapp import puente_meta as pm


@pytest.fixture(autouse=True)
def aislar_estado():
    """Limpia la memoria del puente y restaura funciones monkeypatched."""
    pm.limpiar_estado()
    orig_enviar = pm.enviar_whatsapp
    orig_registrar = pm.registrar
    yield
    pm.limpiar_estado()
    pm.enviar_whatsapp = orig_enviar
    pm.registrar = orig_registrar


def test_carga_plantilla_por_defecto():
    plantilla, negocio = pb.armar_plantilla(None)
    assert plantilla is not None
    assert negocio["NOMBRE_NEGOCIO"] == "Agua Purificada Ejemplo Ficticio"
    assert "Agua Purificada Ejemplo Ficticio" in plantilla
    assert pb.verificar_plantilla(plantilla) is True


def test_carga_plantilla_json_personalizado(tmp_path):
    datos = {
        "NOMBRE_NEGOCIO": "Distribuidora Don Pepe",
        "RUBRO_NEGOCIO": "distribuidora de abarrotes",
        "HORARIOS_ATENCION": "Lunes a viernes 08:00–18:00",
        "REGLA_TRANSFERENCIA_HUMANO": "pasar con Don Pepe",
        "TELEFONO_OFICIAL": "+56 9 8888 7777",
        "ZONAS_REPARTO": "Comuna Centro",
        "DIAS_REPARTO": "martes y jueves",
        "HORA_CORTE": "15:00 del día anterior",
        "SERVICIOS_Y_PRECIOS_CLP": "- Harina 25 kg: $18.000 CLP"
    }
    archivo_json = tmp_path / "negocio.json"
    archivo_json.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    plantilla, neg = pb.armar_plantilla(str(archivo_json))
    assert plantilla is not None
    assert "Distribuidora Don Pepe" in plantilla
    assert pb.verificar_plantilla(plantilla) is True


def test_plantilla_con_datos_sin_llenar_avisa_y_termina(tmp_path, capsys):
    incompleta = tmp_path / "incompleta.txt"
    incompleta.write_text(
        "Eres el bot de {NOMBRE_NEGOCIO}. Repartos: {DIAS_REPARTO}. Pago: [completar con el cliente]",
        encoding="utf-8"
    )

    plantilla, _ = pb.armar_plantilla(str(incompleta))
    assert pb.verificar_plantilla(plantilla) is False

    salida = capsys.readouterr().out
    assert "El bot todavía tiene datos sin llenar" in salida
    assert "{NOMBRE_NEGOCIO}" in salida
    assert "{DIAS_REPARTO}" in salida
    assert "[completar con el cliente]" in salida

    # main() debe terminar con código 1
    assert pb.main(["--plantilla", str(incompleta)]) == 1


def test_plantilla_inexistente_avisa_y_termina(capsys):
    ret = pb.main(["--plantilla", "archivo_no_existente_98765.txt"])
    assert ret == 1
    salida = capsys.readouterr().out
    assert "No encontré la plantilla del bot" in salida


def test_responde_a_un_mensaje_sin_red_y_sin_escribir_en_pedidos_csv(tmp_path):
    pedidos_real = os.path.join(pm.RAIZ, "outputs", "pedidos", "pedidos.csv")
    size_antes = os.path.getsize(pedidos_real) if os.path.exists(pedidos_real) else None
    mtime_antes = os.path.getmtime(pedidos_real) if os.path.exists(pedidos_real) else None

    archivo_temp = str(tmp_path / "pedidos_temp.csv")
    plantilla, negocio = pb.armar_plantilla(None)
    cfg = pb.configurar_puente_consola(negocio=negocio, archivo_pedidos=archivo_temp)

    red_llamada = False

    def red_prohibida(*args, **kwargs):
        nonlocal red_llamada
        red_llamada = True
        raise AssertionError("No debe haber llamadas a la red")

    with mock.patch.object(pm.requests, "post", side_effect=red_prohibida), \
         mock.patch.object(pm, "call_ollama", return_value="¡Hola! Bienvenido al servicio."):
        resp = pb.procesar_linea("Hola buenas", cfg, plantilla)

    assert resp == "¡Hola! Bienvenido al servicio."
    assert not red_llamada, "Se realizó una llamada de red cuando debía ser cero"

    # Verificar que NO se escribió en outputs/pedidos/pedidos.csv
    if size_antes is not None:
        assert os.path.getsize(pedidos_real) == size_antes
        assert os.path.getmtime(pedidos_real) == mtime_antes
    else:
        assert not os.path.exists(pedidos_real)

    # Verificar que el pedido sí se guardó en el archivo temporal
    assert os.path.exists(archivo_temp)
    contenido_temp = open(archivo_temp, encoding="utf-8-sig").read()
    assert "Hola buenas" in contenido_temp
    assert "¡Hola! Bienvenido al servicio." in contenido_temp


def test_primer_mensaje_sin_links(tmp_path):
    archivo_temp = str(tmp_path / "pedidos_temp.csv")
    plantilla, negocio = pb.armar_plantilla(None)
    cfg = pb.configurar_puente_consola(negocio=negocio, archivo_pedidos=archivo_temp)

    # Primer mensaje: quita el enlace
    with mock.patch.object(pm, "call_ollama", return_value="¡Hola! Visita https://tienda.cl para pedir"):
        resp1 = pb.procesar_linea("hola", cfg, plantilla)
    assert "https://tienda.cl" not in resp1
    assert "tienda.cl" not in resp1

    # Segundo mensaje: no es el primer mensaje, conserva enlaces si el modelo los genera
    with mock.patch.object(pm, "call_ollama", return_value="Aquí está el link: https://tienda.cl"):
        resp2 = pb.procesar_linea("dame el link", cfg, plantilla)
    assert "https://tienda.cl" in resp2


def test_memoria_conversacion_previa(tmp_path):
    archivo_temp = str(tmp_path / "pedidos_temp.csv")
    plantilla, negocio = pb.armar_plantilla(None)
    cfg = pb.configurar_puente_consola(negocio=negocio, archivo_pedidos=archivo_temp)

    prompts_enviados = []

    def mock_ollama(prompt, **kwargs):
        prompts_enviados.append(prompt)
        return "Respuesta simulada"

    with mock.patch.object(pm, "call_ollama", side_effect=mock_ollama):
        pb.procesar_linea("quiero 2 bidones", cfg, plantilla)
        pb.procesar_linea("calle Los Aromos 123", cfg, plantilla)

    assert len(prompts_enviados) == 2
    # El segundo prompt debe incluir el historial de la conversación
    assert "Conversación anterior:" in prompts_enviados[1]
    assert "Cliente: quiero 2 bidones" in prompts_enviados[1]
    assert "calle Los Aromos 123" in prompts_enviados[1]


def test_deriva_a_persona_y_pausa_hasta_menu(tmp_path):
    archivo_temp = str(tmp_path / "pedidos_temp.csv")
    plantilla, negocio = pb.armar_plantilla(None)
    cfg = pb.configurar_puente_consola(negocio=negocio, archivo_pedidos=archivo_temp)

    # 1. El cliente pide una persona
    with mock.patch.object(pm, "call_ollama", return_value="¡Hola! ¿En qué te ayudo?"):
        resp1 = pb.procesar_linea("quiero hablar con una persona", cfg, plantilla)

    assert "persona del equipo" in resp1
    assert pm.en_pausa(pb.TEL_PRUEBA) is True

    # 2. El cliente sigue escribiendo: el bot está en pausa y no responde
    with mock.patch.object(pm, "call_ollama") as mock_ollama:
        resp2 = pb.procesar_linea("¿hay alguien?", cfg, plantilla)
        assert resp2 is None
        mock_ollama.assert_not_called()

    # 3. El cliente escribe 'menú': se reactiva la pausa y el bot responde
    with mock.patch.object(pm, "call_ollama", return_value="Menú: 1. 2. 3. 4."):
        resp3 = pb.procesar_linea("menú", cfg, plantilla)

    assert resp3 == "Menú: 1. 2. 3. 4."
    assert pm.en_pausa(pb.TEL_PRUEBA) is False


def test_salir_termina_chat(capsys):
    plantilla, negocio = pb.armar_plantilla(None)
    cfg = pb.configurar_puente_consola(negocio=negocio)

    entradas = iter(["hola", "salir"])

    with mock.patch.object(pm, "call_ollama", return_value="Hola, ¿en qué te ayudo?"):
        pb.chat_interactivo(cfg, plantilla, negocio, lector_input=lambda _: next(entradas))

    salida = capsys.readouterr().out
    assert "Conversación finalizada." in salida


def test_main_flujo_completo(capsys):
    entradas = iter(["salir"])
    with mock.patch("builtins.input", lambda _: next(entradas)):
        ret = pb.main([])

    assert ret == 0
    salida = capsys.readouterr().out
    assert "--- Probador del Bot de Pedidos (Demo Local sin WhatsApp) ---" in salida
    assert "Agua Purificada Ejemplo Ficticio" in salida
    assert "Conversación finalizada." in salida
