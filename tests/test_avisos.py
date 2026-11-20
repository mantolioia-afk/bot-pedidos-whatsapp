import json
import urllib.error
import urllib.request

from src.whatsapp.avisos import armar_resumen, avisar_dueno


def _prohibido(*a, **k):
    raise AssertionError("no debía llamar a la red")


class _MockResponse:
    def __init__(self, status=200):
        self.status = status

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_ninguno_no_envia(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _prohibido)
    assert avisar_dueno("x", {}) is False
    assert avisar_dueno("x", {"CANAL_AVISO": "ninguno"}) is False


def test_canal_desconocido_no_falla(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _prohibido)
    assert avisar_dueno("x", {"CANAL_AVISO": "otro_canal"}) is False
    assert avisar_dueno("x", {"CANAL_AVISO": "telegram"}) is False


def test_resumen_sin_numero_completo():
    r = armar_resumen("56911112222", "2 bidones\npara mañana")
    assert "56911112222" not in r
    assert r == "Pedido nuevo ...2222: 2 bidones para mañana"


def test_resumen_pide_persona():
    r1 = armar_resumen("56911112222", "hola, necesito hablar con una persona")
    assert "Pide hablar con una persona" in r1
    assert "...2222" in r1
    assert "56911112222" not in r1

    r2 = armar_resumen("56911112222", "urgente", tipo="Pide hablar con una persona")
    assert "Pide hablar con una persona" in r2


def test_resumen_hora_y_fuera_horario():
    r = armar_resumen("56911112222", "2 bidones", hora="22:15", fuera_horario=True)
    assert "22:15" in r
    assert "fuera de horario" in r
    assert "...2222" in r
    assert "2 bidones" in r
    assert "56911112222" not in r


def test_resumen_max_300_caracteres():
    texto_largo = "a" * 400
    r = armar_resumen("56911112222", texto_largo)
    assert ("a" * 300) in r
    assert ("a" * 301) not in r


def test_telegram_envia_datos_correctos(monkeypatch):
    llamadas = []

    def mock_urlopen(req, timeout=None):
        llamadas.append((req, timeout))
        return _MockResponse(200)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    cfg = {
        "CANAL_AVISO": "telegram",
        "TELEGRAM_TOKEN": "123456:ABC-DEF",
        "TELEGRAM_CHAT_ID": "987654321",
    }
    resumen = "Pedido nuevo ...1234: 2 bidones"
    resultado = avisar_dueno(resumen, cfg)

    assert resultado is True
    assert len(llamadas) == 1
    req, timeout = llamadas[0]
    assert timeout == 10
    assert req.full_url == "https://api.telegram.org/bot123456:ABC-DEF/sendMessage"
    assert req.headers.get("Content-type") == "application/json"

    datos = json.loads(req.data.decode("utf-8"))
    assert datos["chat_id"] == "987654321"
    assert datos["text"] == resumen


def test_telegram_sin_token_o_chat_id_no_se_cae(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _prohibido)

    assert avisar_dueno("x", {"CANAL_AVISO": "telegram", "TELEGRAM_TOKEN": "t"}) is False
    assert avisar_dueno("x", {"CANAL_AVISO": "telegram", "TELEGRAM_CHAT_ID": "c"}) is False
    assert avisar_dueno("x", {"CANAL_AVISO": "telegram"}) is False


def test_telegram_falla_red_no_se_cae_y_no_imprime_token(monkeypatch, capsys):
    secreto = "TOKEN_SECRETO_PRUEBA_998877"

    def mock_urlopen_fallo(req, timeout=None):
        raise urllib.error.URLError(f"fallo de conexión simulado a api.telegram.org/bot{secreto}/sendMessage")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_fallo)

    cfg = {
        "CANAL_AVISO": "telegram",
        "TELEGRAM_TOKEN": secreto,
        "TELEGRAM_CHAT_ID": "123",
    }
    resultado = avisar_dueno("msg", cfg)
    assert resultado is False

    cap = capsys.readouterr()
    assert secreto not in cap.out
    assert secreto not in cap.err


def test_comentario_seguridad_no_imprimir_excepcion():
    from pathlib import Path
    codigo = Path("src/whatsapp/avisos.py").read_text(encoding="utf-8")
    assert "NO imprimir la excepción: trae el token" in codigo


def test_resumen_aviso_sin_texto_por_parametro():
    r = armar_resumen("56911112222", "2 bidones para mañana", sin_texto=True)
    assert r == "Pedido nuevo de ...2222, revisa la lista"
    assert "2 bidones" not in r


def test_resumen_aviso_sin_texto_por_env(monkeypatch):
    monkeypatch.setenv("AVISO_SIN_TEXTO", "1")
    r = armar_resumen("56911112222", "2 bidones para mañana")
    assert r == "Pedido nuevo de ...2222, revisa la lista"
    assert "2 bidones" not in r


def test_resumen_aviso_sin_texto_por_cfg():
    cfg = {"AVISO_SIN_TEXTO": "1"}
    r = armar_resumen("56911112222", "2 bidones para mañana", cfg=cfg)
    assert r == "Pedido nuevo de ...2222, revisa la lista"
    assert "2 bidones" not in r


def test_resumen_aviso_sin_texto_pide_persona():
    r = armar_resumen("56911112222", "necesito hablar con una persona", sin_texto=True)
    assert r == "Pide hablar con una persona de ...2222, revisa la lista"
    assert "necesito" not in r


def test_resumen_aviso_sin_texto_cero_o_falso_mantiene_texto(monkeypatch):
    monkeypatch.setenv("AVISO_SIN_TEXTO", "0")
    r = armar_resumen("56911112222", "2 bidones")
    assert r == "Pedido nuevo ...2222: 2 bidones"

    r2 = armar_resumen("56911112222", "2 bidones", sin_texto=False)
    assert r2 == "Pedido nuevo ...2222: 2 bidones"


def test_telegram_http_error_no_imprime_token(monkeypatch, capsys):
    secreto = "TOKEN_SECRETO_HTTP_5544"

    def mock_urlopen_http(req, timeout=None):
        raise urllib.error.HTTPError(
            f"https://api.telegram.org/bot{secreto}/sendMessage",
            400,
            "Bad Request",
            {},
            None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_http)

    cfg = {
        "CANAL_AVISO": "telegram",
        "TELEGRAM_TOKEN": secreto,
        "TELEGRAM_CHAT_ID": "123",
    }
    resultado = avisar_dueno("msg", cfg)
    assert resultado is False

    cap = capsys.readouterr()
    assert secreto not in cap.out
    assert secreto not in cap.err


def test_telegram_status_error_no_se_cae(monkeypatch):
    def mock_urlopen_status_500(req, timeout=None):
        return _MockResponse(500)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_status_500)

    cfg = {
        "CANAL_AVISO": "telegram",
        "TELEGRAM_TOKEN": "tok",
        "TELEGRAM_CHAT_ID": "chat",
    }
    assert avisar_dueno("msg", cfg) is False
