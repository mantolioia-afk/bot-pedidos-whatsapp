from datetime import datetime
from src.whatsapp.horario import ahora_chile, estado_horario, linea_contexto

H = "lun-vie 09:00-20:00; sab 09:00-14:00"


def test_abierto_martes_mediodia():
    assert estado_horario(datetime(2026, 11, 17, 12, 0), H) == "abierto"


def test_cerrado_a_la_hora_justa():
    assert estado_horario(datetime(2026, 11, 17, 20, 0), H) == "cerrado"


def test_cerrado_domingo():
    assert estado_horario(datetime(2026, 11, 22, 10, 0), H) == "cerrado"


def test_sabado_tarde_cerrado():
    assert estado_horario(datetime(2026, 11, 21, 15, 0), H) == "cerrado"


def test_vacio_es_desconocido():
    assert estado_horario(datetime(2026, 11, 17, 12, 0), "") == "desconocido"


def test_mal_escrito_es_desconocido():
    assert estado_horario(datetime(2026, 11, 17, 12, 0), "todo el día") == "desconocido"


def test_linea_cerrado_dice_manana():
    assert "mañana" in linea_contexto("cerrado")


def test_linea_desconocido_vacia():
    assert linea_contexto("desconocido") == ""


def test_linea_abierto():
    assert linea_contexto("abierto") == "(Ahora el negocio está ABIERTO.)"


def test_abierto_sabado_manana():
    assert estado_horario(datetime(2026, 11, 21, 10, 0), H) == "abierto"


def test_abierto_a_la_hora_de_inicio():
    assert estado_horario(datetime(2026, 11, 17, 9, 0), H) == "abierto"


def test_cerrado_antes_de_abrir():
    assert estado_horario(datetime(2026, 11, 17, 8, 59), H) == "cerrado"


def test_ahora_chile_devuelve_datetime():
    assert isinstance(ahora_chile(), datetime)


def test_cargar_config_lee_horario(monkeypatch):
    from src.whatsapp.puente_meta import cargar_config
    monkeypatch.setenv("HORARIO_ATENCION", H)
    cfg, _ = cargar_config()
    assert cfg.get("HORARIO_ATENCION") == H


def test_responder_lote_antepone_linea_contexto_cerrado(monkeypatch):
    import src.whatsapp.puente_meta as pm
    pm.limpiar_estado()

    # Simular domingo a las 10:00 (cerrado)
    monkeypatch.setattr("src.whatsapp.puente_meta.ahora_chile", lambda: datetime(2026, 11, 22, 10, 0))

    captura_prompt = {}

    def mock_generar_respuesta(mensaje, plantilla):
        captura_prompt["prompt"] = mensaje["text"]
        return "Respuesta simulada"

    monkeypatch.setattr(pm, "generar_respuesta", mock_generar_respuesta)
    monkeypatch.setattr(pm, "enviar_whatsapp", lambda *a, **k: True)

    cfg = {"HORARIO_ATENCION": H, "TELEFONO_OFICIAL": ""}
    pm.responder_lote("56911112222", ["Quiero 2 bidones"], False, cfg, "plantilla")

    esperado_ctx = linea_contexto("cerrado")
    assert esperado_ctx in captura_prompt["prompt"]
    assert "Quiero 2 bidones" in captura_prompt["prompt"]
    assert captura_prompt["prompt"].startswith(esperado_ctx)
