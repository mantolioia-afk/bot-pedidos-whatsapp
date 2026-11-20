import csv
from datetime import datetime

from src.whatsapp.registro_pedidos import ENCABEZADO, anotar

M = datetime(2026, 11, 18, 10, 30)


def _filas(ruta):
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_crea_archivo_con_encabezado(tmp_path):
    ruta = tmp_path / "pedidos" / "pedidos.csv"
    anotar(str(ruta), "56911112222", "2 bidones", "Te confirma una persona", False, "abierto", M)
    assert _filas(ruta)[0] == ENCABEZADO


def test_texto_con_comas_y_saltos(tmp_path):
    ruta = tmp_path / "p.csv"
    texto = '2 bidones, calle Sol 12\nporfa "rápido"'
    anotar(str(ruta), "569", texto, "ok", False, "cerrado", M)
    filas = _filas(ruta)
    assert len(filas) == 2
    assert filas[1][2] == texto


def test_dos_anotaciones_agregan(tmp_path):
    ruta = tmp_path / "p.csv"
    anotar(str(ruta), "569", "a", "b", False, "abierto", M)
    anotar(str(ruta), "569", "c", "d", True, "abierto", M)
    filas = _filas(ruta)
    assert len(filas) == 3
    assert filas[2][4] == "si"


def test_estado_pendiente(tmp_path):
    ruta = tmp_path / "p.csv"
    anotar(str(ruta), "569", "a", "b", False, "desconocido", M)
    assert _filas(ruta)[1][ENCABEZADO.index("estado")] == "pendiente"


# --- limpiar pedidos viejos ---
from datetime import timedelta  # noqa: E402

from src.whatsapp.registro_pedidos import limpiar_viejos  # noqa: E402


def test_limpiar_borra_viejos_y_conserva_nuevos(tmp_path):
    ruta = str(tmp_path / "p.csv")
    anotar(ruta, "569111", "viejo", "r", False, "abierto", M - timedelta(days=100))
    anotar(ruta, "569222", "nuevo", "r", False, "abierto", M - timedelta(days=5))
    assert limpiar_viejos(ruta, 90, ahora=M) == 1
    filas = _filas(ruta)
    assert filas[0] == ENCABEZADO
    assert [f[2] for f in filas[1:]] == ["nuevo"]
    with open(ruta, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"
    anotar(ruta, "569333", "otro", "r", False, "abierto", M)
    assert [f[2] for f in _filas(ruta)[1:]] == ["nuevo", "otro"]


def test_limpiar_archivo_inexistente_y_vacio(tmp_path):
    assert limpiar_viejos(str(tmp_path / "no.csv"), 90, ahora=M) == 0
    vacio = tmp_path / "vacio.csv"
    vacio.write_text("")
    assert limpiar_viejos(str(vacio), 90, ahora=M) == 0


def test_limpiar_conserva_filas_rotas(tmp_path):
    ruta = str(tmp_path / "p.csv")
    anotar(ruta, "569111", "viejo", "r", False, "abierto", M - timedelta(days=200))
    with open(ruta, "a", encoding="utf-8", newline="") as f:
        f.write("fecha-mala,569,x\n\nsolo\n")
    assert limpiar_viejos(ruta, 90, ahora=M) == 1
    datos = [f for f in _filas(ruta)[1:] if f]
    assert datos == [["fecha-mala", "569", "x"], ["solo"]]


def test_limpiar_dias_desde_env(tmp_path, monkeypatch):
    ruta = str(tmp_path / "p.csv")
    anotar(ruta, "569111", "x", "r", False, "abierto", M - timedelta(days=10))
    monkeypatch.setenv("DIAS_GUARDAR_PEDIDOS", "7")
    assert limpiar_viejos(ruta, ahora=M) == 1


# ---------- último pedido de un cliente ----------
def _csv56(tmp_path, filas):
    from datetime import datetime as _dt
    from src.whatsapp import registro_pedidos as rp
    ruta = str(tmp_path / "p56.csv")
    for tel, texto in filas:
        rp.anotar(ruta, tel, texto, "ok", False, "abierto", _dt(2026, 11, 10, 10, 0))
    return ruta


def test_ultimo_pedido_ignora_saludos_y_repetir(tmp_path):
    from src.whatsapp import registro_pedidos as rp
    ruta = _csv56(tmp_path, [("569A", "2 bidones"), ("569B", "1 caja"), ("569A", "Hola"),
                             ("569A", "lo mismo de siempre")])
    assert rp.ultimo_pedido(ruta, "569A") == "2 bidones"
    assert rp.ultimo_pedido(ruta, "569B") == "1 caja"


def test_ultimo_pedido_sin_datos(tmp_path):
    from src.whatsapp import registro_pedidos as rp
    assert rp.ultimo_pedido(str(tmp_path / "no.csv"), "569A") is None
    ruta = _csv56(tmp_path, [("569A", "hola")])
    assert rp.ultimo_pedido(ruta, "569A") is None
    assert rp.ultimo_pedido(ruta, "569Z") is None


def test_ultimo_pedido_fila_rota(tmp_path):
    from src.whatsapp import registro_pedidos as rp
    ruta = _csv56(tmp_path, [("569A", "2 bidones")])
    with open(ruta, "a", encoding="utf-8") as f:
        f.write("rota\n")
    assert rp.ultimo_pedido(ruta, "569A") == "2 bidones"


def test_pide_repetir():
    from src.whatsapp import registro_pedidos as rp
    for t in ["Lo mismo de siempre", "lo de siempre porfa", "lo mismo que la otra vez", "Repetir pedido"]:
        assert rp.pide_repetir(t)
    assert not rp.pide_repetir("2 bidones")


# ---------- protección de fórmulas y limpieza periódica ----------
from src.whatsapp.registro_pedidos import (  # noqa: E402
    limpiar_al_arrancar,
    limpiar_diario,
    sanitizar_celda,
)


def test_sanitizar_celda_formulas():
    # Caracteres de fórmula al inicio
    assert sanitizar_celda('=HYPERLINK("x")') == '\'=HYPERLINK("x")'
    assert sanitizar_celda("+56 9 1234 5678", es_telefono=False) == "'+56 9 1234 5678"
    assert sanitizar_celda("-10") == "'-10"
    assert sanitizar_celda("@usuario") == "'@usuario"
    assert sanitizar_celda("\tdato") == "'\tdato"
    assert sanitizar_celda("\rdato") == "'\rdato"
    assert sanitizar_celda("\ndato") == "'\ndato"

    # Columna teléfono: se exceptúa '+' para formato internacional E.164
    assert sanitizar_celda("+56 9 1234 5678", es_telefono=True) == "+56 9 1234 5678"
    assert sanitizar_celda("+56911112222", es_telefono=True) == "+56911112222"
    # Pero si el teléfono empieza con fórmula peligrosa, sí se protege
    assert sanitizar_celda("=cmd", es_telefono=True) == "'=cmd"
    assert sanitizar_celda("-569", es_telefono=True) == "'-569"

    # Valores normales o vacíos no se alteran
    assert sanitizar_celda("2 bidones") == "2 bidones"
    assert sanitizar_celda("abierto") == "abierto"
    assert sanitizar_celda("") == ""
    assert sanitizar_celda(None) == ""


def test_anotar_escapa_formulas_en_csv(tmp_path):
    ruta = tmp_path / "p_formulas.csv"
    # Inyección en mensaje de cliente y fórmula en respuesta del bot
    anotar(str(ruta), "+56 9 1234 5678", '=HYPERLINK("http://malicioso.com")',
           "=1+1", False, "abierto", M)
    filas = _filas(ruta)
    assert len(filas) == 2
    # El teléfono con '+' se conserva intacto
    assert filas[1][1] == "+56 9 1234 5678"
    # El texto del cliente y la respuesta del bot quedan escapados con comilla simple
    assert filas[1][2] == '\'=HYPERLINK("http://malicioso.com")'
    assert filas[1][3] == "'=1+1"


def test_anotar_escapa_mensaje_con_mas_56(tmp_path):
    ruta = tmp_path / "p_mas56.csv"
    # Si el cliente escribe "+56 9..." en el cuerpo del mensaje, sí se escapa
    anotar(str(ruta), "56911112222", "+56 9 1234 5678", "ok", False, "abierto", M)
    filas = _filas(ruta)
    assert filas[1][2] == "'+56 9 1234 5678"


def test_limpiar_al_arrancar_borra_archivo_tmp(tmp_path):
    ruta = tmp_path / "pedidos.csv"
    anotar(str(ruta), "569111", "pedido", "r", False, "abierto", M)
    tmp = tmp_path / "pedidos.csv.tmp"
    tmp.write_text("archivo temporal residual de un corte")
    assert tmp.exists()

    limpiar_al_arrancar(str(ruta))
    assert not tmp.exists()


def test_limpiar_diario_maximo_una_vez_cada_24_horas(tmp_path):
    ruta = str(tmp_path / "pedidos_diario.csv")
    t0 = datetime(2026, 11, 1, 10, 0)

    # 1 pedido viejo (hace 100 días) y 1 reciente
    anotar(ruta, "569111", "viejo", "r", False, "abierto", t0 - timedelta(days=100))
    anotar(ruta, "569222", "reciente", "r", False, "abierto", t0 - timedelta(days=5))

    # Primera llamada a t0: limpia el viejo
    borrados = limpiar_diario(ruta, ahora=t0)
    assert borrados == 1
    assert [f[2] for f in _filas(ruta)[1:]] == ["reciente"]

    # Agregamos otro pedido viejo
    anotar(ruta, "569333", "otro_viejo", "r", False, "abierto", t0 - timedelta(days=120))

    # Llamada 5 horas después (< 24h): NO debe limpiar (máximo una vez cada 24 horas)
    t1 = t0 + timedelta(hours=5)
    borrados = limpiar_diario(ruta, ahora=t1)
    assert borrados == 0
    # "otro_viejo" sigue presente
    assert [f[2] for f in _filas(ruta)[1:]] == ["reciente", "otro_viejo"]

    # Llamada 25 horas después de t0 (> 24h): SÍ debe limpiar
    t2 = t0 + timedelta(hours=25)
    borrados = limpiar_diario(ruta, ahora=t2)
    assert borrados == 1
    # "otro_viejo" fue borrado
    assert [f[2] for f in _filas(ruta)[1:]] == ["reciente"]

    # Llamada inmediata 1 minuto después (< 24h desde t2): no limpia
    t3 = t2 + timedelta(minutes=1)
    assert limpiar_diario(ruta, ahora=t3) == 0


def test_puente_anotar_ejecuta_limpieza_diaria(tmp_path):
    from src.whatsapp import puente_meta as pm
    ruta = str(tmp_path / "pedidos_pm.csv")
    cfg = {"ARCHIVO_PEDIDOS": ruta}
    t0 = datetime(2026, 11, 1, 10, 0)

    anotar(ruta, "569111", "viejo", "r", False, "abierto", t0 - timedelta(days=100))
    # Al llamar _anotar_y_avisar con t0, se dispara limpiar_diario
    pm._anotar_y_avisar("569222", "nuevo", "ok", False, "abierto", t0, cfg)
    filas = _filas(ruta)
    assert len(filas) == 2  # encabezado + nuevo (el viejo fue borrado)
    assert filas[1][1] == "569222"

