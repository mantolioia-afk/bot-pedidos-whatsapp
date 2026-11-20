"""puente de PRUEBA entre WhatsApp Cloud API (oficial de Meta) y el bot en Ollama.

Uso: python -m src.whatsapp.puente_meta
Solo para el modo prueba de Meta . Las claves van en `.env`, nunca en el código.
"""
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from src.core.llm_router import call_ollama
from src.whatsapp import avisos, registro_pedidos
from src.whatsapp.horario import ahora_chile, estado_horario, linea_contexto

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLANTILLA_DEFECTO = os.path.join(
    "brain", "moldes_maestros", "bot_a_pedidos", "system_prompt_template.md"
)
# Modelo para hablar con clientes: gemma3:4b fue el más preciso.
MODELO_DEFECTO = "gemma3:4b"
ESPERA_MODELO_SEGUNDOS = 90
OBLIGATORIAS = ("META_VERIFY_TOKEN", "META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID", "META_APP_SECRET")
URL_API = "https://graph.facebook.com/v21.0/{}/messages"

MSG_SOLO_TEXTO = "Por ahora solo puedo leer mensajes de texto. Si necesitas algo más, te paso con una persona."
MSG_ERROR = "Disculpa, tuve un problema. Una persona te contestará pronto."

_vistos = OrderedDict()
_vistos_lock = threading.Lock()
MAX_VISTOS = 500


# ---------- configuración ----------
def leer_env(ruta=None):
    """Lector simple de .env (CLAVE=valor). No pisa variables ya definidas."""
    ruta = ruta or os.path.join(RAIZ, ".env")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def cargar_config():
    """Devuelve (config, faltantes)."""
    faltan = [v for v in OBLIGATORIAS if not os.environ.get(v)]
    cfg = {v: os.environ.get(v, "") for v in OBLIGATORIAS}
    cfg["BOT_PLANTILLA"] = os.environ.get("BOT_PLANTILLA") or PLANTILLA_DEFECTO
    cfg["PUERTO"] = int(os.environ.get("PUERTO") or 8080)
    cfg["ESPERA_SEGUNDOS"] = float(os.environ.get("ESPERA_SEGUNDOS") or 8)
    cfg["PAUSA_HORAS"] = float(os.environ.get("PAUSA_HORAS") or 4)
    cfg["LIMITE_POR_HORA"] = int(os.environ.get("LIMITE_POR_HORA") or 20)
    cfg["TELEFONO_OFICIAL"] = os.environ.get("TELEFONO_OFICIAL", "")
    cfg["HORARIO_ATENCION"] = os.environ.get("HORARIO_ATENCION", "")
    cfg["ARCHIVO_PEDIDOS"] = os.environ.get("ARCHIVO_PEDIDOS", "")
    cfg["CANAL_AVISO"] = os.environ.get("CANAL_AVISO") or "ninguno"
    cfg["AVISO_SIN_TEXTO"] = os.environ.get("AVISO_SIN_TEXTO", "")
    return cfg, faltan


def leer_plantilla(ruta):
    if not os.path.isabs(ruta):
        ruta = os.path.join(RAIZ, ruta)
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def datos_sin_llenar(plantilla: str) -> list:
    """Marcadores como {DIAS_REPARTO} o textos '[completar con el cliente]' que el cliente vería."""
    marcadores = sorted(set(re.findall(r"\{[A-Z_]+\}", plantilla)))
    if "[completar con el cliente]" in plantilla:
        marcadores.append("[completar con el cliente]")
    return marcadores


# ---------- lógica (probada sin red) ----------
def verificar_suscripcion(query: dict, verify_token: str):
    """GET /webhook. Devuelve (codigo, cuerpo)."""
    modo = (query.get("hub.mode") or [""])[0]
    token = (query.get("hub.verify_token") or [""])[0]
    reto = (query.get("hub.challenge") or [""])[0]
    if modo == "subscribe" and verify_token and hmac.compare_digest(token, verify_token):
        return 200, reto
    return 403, "prohibido"


def firma_valida(cuerpo: bytes, cabecera: str, app_secret: str) -> bool:
    if not cabecera or not app_secret or not cabecera.startswith("sha256="):
        return False
    esperada = hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(cabecera[len("sha256="):], esperada)


def extraer_mensajes(datos: dict):
    """Lista de mensajes entrantes [{id, from, type, text}]."""
    salida = []
    for entry in datos.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            for m in (change.get("value") or {}).get("messages", []) or []:
                salida.append({
                    "id": m.get("id", ""),
                    "from": m.get("from", ""),
                    "type": m.get("type", ""),
                    "text": (m.get("text") or {}).get("body", ""),
                })
    return salida


def ya_visto(msg_id: str) -> bool:
    """True si el mensaje ya se procesó; si no, lo marca como visto."""
    with _vistos_lock:
        if msg_id in _vistos:
            return True
        _vistos[msg_id] = True
        while len(_vistos) > MAX_VISTOS:
            _vistos.popitem(last=False)
        return False


def generar_respuesta(mensaje: dict, plantilla: str) -> str:
    if mensaje["type"] != "text":
        return MSG_SOLO_TEXTO
    try:
        resp = call_ollama(
            prompt=mensaje["text"],
            system_prompt=plantilla,
            model=os.environ.get("BOT_MODELO") or MODELO_DEFECTO,
            timeout=ESPERA_MODELO_SEGUNDOS,
            formato_json=False,
        )
    except Exception:
        resp = None
    resp = (resp or "").strip()
    return resp or MSG_ERROR


def enviar_whatsapp(para: str, texto: str, cfg: dict) -> bool:
    try:
        r = requests.post(
            URL_API.format(cfg["META_PHONE_NUMBER_ID"]),
            headers={"Authorization": f"Bearer {cfg['META_ACCESS_TOKEN']}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": para, "type": "text",
                  "text": {"body": texto[:4096]}},
            timeout=15,
        )
        return 200 <= r.status_code < 300
    except requests.RequestException:
        return False


def registrar(para: str, ok: bool):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} ...{para[-4:]} {'ok' if ok else 'error'}", flush=True)


# ---------- juntar mensajes, memoria corta y pausa para el dueño ----------
MAX_TURNOS = 10
MEMORIA_SEGUNDOS = 2 * 3600
MAX_NUMEROS = 500
PALABRAS_REACTIVAR = ("menu", "menú")

_estado_lock = threading.Lock()
_esperas = {}               # telefono -> {"textos": [...], "no_texto": bool, "timer": Timer}
_memoria = OrderedDict()    # telefono -> {"turnos": [(cliente, bot)], "ultimo": t}
_pausas = {}                # telefono -> momento en que termina la pausa
_locks_numero = {}          # telefono -> Lock (responde en orden, un número no bloquea a otro)
_respuestas = OrderedDict() # telefono -> {"tiempos": [t, ...], "avisado": bool} (límite por hora)
MSG_LIMITE = "Recibí muchos mensajes seguidos, una persona te contestará pronto."


def _ahora():
    return time.monotonic()


def limpiar_estado():
    """Borra esperas, memoria y pausas (para pruebas o reinicio)."""
    with _estado_lock:
        for e in _esperas.values():
            if e.get("timer"):
                e["timer"].cancel()
        _esperas.clear()
        _memoria.clear()
        _pausas.clear()
        _locks_numero.clear()
        _respuestas.clear()


def _lock_de(tel):
    with _estado_lock:
        return _locks_numero.setdefault(tel, threading.Lock())


def en_pausa(tel) -> bool:
    with _estado_lock:
        fin = _pausas.get(tel)
        if fin is None:
            return False
        if _ahora() >= fin:
            del _pausas[tel]
            return False
        return True


def _pausar(tel, cfg):
    horas = float(cfg.get("PAUSA_HORAS", 4))
    with _estado_lock:
        _pausas[tel] = _ahora() + horas * 3600


def _quitar_pausa(tel):
    with _estado_lock:
        _pausas.pop(tel, None)


def _solo_digitos(s):
    return "".join(c for c in (s or "") if c.isdigit())


MSG_PRECIOS = "Para precios y promociones te confirma una persona del equipo."
_PALABRAS_RIESGO = ("descuento", "gratis", "regalo", "promocion", "%")
_PRECIO = re.compile(r"\$\s*(\d[\d.]*)")


def _normalizar(s: str) -> str:
    """Minúsculas y sin tildes."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _precios(s: str) -> set:
    return {p.replace(".", "").lstrip("0") for p in _PRECIO.findall(s or "")}


def respuesta_segura(respuesta: str, plantilla: str) -> bool:
    """False si la IA promete descuentos o precios que no están en la plantilla."""
    r, p = _normalizar(respuesta), _normalizar(plantilla)
    if any(w in r and w not in p for w in _PALABRAS_RIESGO):
        return False
    return _precios(respuesta) <= _precios(plantilla)


def deriva_a_persona(respuesta: str, telefono_oficial: str = "") -> bool:
    """True si la respuesta del bot pasa al cliente con una persona."""
    if respuesta in (MSG_ERROR, MSG_PRECIOS):
        return True
    tel = _solo_digitos(telefono_oficial)
    if len(tel) >= 8 and tel in _solo_digitos(respuesta):
        return True
    r = respuesta.lower()
    return "una persona del equipo" in r and ("derivo" in r or "te paso" in r)


_PIDE_PERSONA = re.compile(
    r"\b(hablar|habla|comunicar|contactar|atender|atienda|pasa|p[aá]same|p[aá]sa me)\b.*"
    r"\b(persona|humano|alguien|due[nñ]o|due[nñ]a|encargad[oa]|ejecutiv[oa])\b"
    r"|\b(atender|atienda|atiende)\s+alguien\b",
    re.IGNORECASE)


def pide_persona(texto: str) -> bool:
    """True si el cliente pide hablar con una persona (no depende de la IA)."""
    return bool(_PIDE_PERSONA.search(texto or ""))


def mensaje_derivar(cfg) -> str:
    tel = cfg.get("TELEFONO_OFICIAL", "")
    base = "Claro, te paso con una persona del equipo. Te responderá apenas pueda."
    return f"{base} Si es urgente, llama al {tel}." if tel else base


def _historial(tel):
    with _estado_lock:
        mem = _memoria.get(tel)
        if not mem:
            return []
        if _ahora() - mem["ultimo"] > MEMORIA_SEGUNDOS:
            del _memoria[tel]
            return []
        return list(mem["turnos"])


def _recordar(tel, cliente, bot):
    with _estado_lock:
        mem = _memoria.pop(tel, None) or {"turnos": []}
        mem["turnos"] = (mem["turnos"] + [(cliente, bot)])[-MAX_TURNOS:]
        mem["ultimo"] = _ahora()
        _memoria[tel] = mem  # queda al final: es el más reciente
        while len(_memoria) > MAX_NUMEROS:
            _memoria.popitem(last=False)


def armar_prompt(historial, texto_nuevo):
    if not historial:
        return texto_nuevo
    previas = "\n".join(f"Cliente: {c}\nRespuesta: {b}" for c, b in historial)
    return f"Conversación anterior:\n{previas}\n\nMensajes nuevos del cliente:\n{texto_nuevo}"


def _revisar_limite(tel, cfg) -> str:
    """Cuenta respuestas por número en la última hora.
    Devuelve "ok", "avisar" (primera vez que se pasa) o "callar" (ya se avisó)."""
    limite = int(cfg.get("LIMITE_POR_HORA", 20))
    ahora = _ahora()
    with _estado_lock:
        reg = _respuestas.pop(tel, None) or {"tiempos": [], "avisado": False}
        reg["tiempos"] = [t for t in reg["tiempos"] if ahora - t < 3600]
        if len(reg["tiempos"]) < limite:
            reg["tiempos"].append(ahora)
            reg["avisado"] = False
            estado = "ok"
        else:
            estado = "callar" if reg["avisado"] else "avisar"
            reg["avisado"] = True
        _respuestas[tel] = reg  # queda al final: es el más reciente
        while len(_respuestas) > MAX_NUMEROS:
            _respuestas.popitem(last=False)
    return estado


def responder_lote(tel, textos, no_texto, cfg, plantilla):
    """Responde UNA vez a todos los mensajes juntados de un número."""
    with _lock_de(tel):
        limite = _revisar_limite(tel, cfg)
        if limite != "ok":
            if limite == "avisar":
                registrar(tel, enviar_whatsapp(tel, MSG_LIMITE, cfg))
            _pausar(tel, cfg)
            return
        if not textos:
            respuesta = MSG_SOLO_TEXTO
        else:
            texto = "\n".join(textos)
            if no_texto:
                texto += "\n(El cliente también envió un audio o imagen que no puedes ver.)"
            momento = ahora_chile()
            horario = estado_horario(momento, cfg.get("HORARIO_ATENCION", ""))
            ctx = linea_contexto(horario)
            historial = _historial(tel)
            anterior = "" if historial else _pedido_anterior(tel, texto, cfg)
            if anterior:
                # La IA ignoraba el pedido anterior (medición 18-11): respuesta fija y segura.
                respuesta = anterior
            else:
                respuesta = generar_respuesta(
                    {"type": "text", "text": armar_prompt(historial, f"{ctx}\n{texto}" if ctx else texto)},
                    plantilla)
            if not historial:  # primer mensaje: nunca con links
                respuesta = quitar_links(respuesta) or MSG_ERROR
            if not anterior and not respuesta_segura(respuesta, plantilla):
                respuesta = MSG_PRECIOS  # la IA no puede inventar precios ni descuentos
            if pide_persona(texto) and not deriva_a_persona(respuesta, cfg.get("TELEFONO_OFICIAL", "")):
                respuesta = mensaje_derivar(cfg)  # la IA a veces no deriva: aquí es seguro
            _recordar(tel, texto, respuesta)  # sin la línea de horario: esa vale solo para este momento
        registrar(tel, enviar_whatsapp(tel, respuesta, cfg))
        derivado = deriva_a_persona(respuesta, cfg.get("TELEFONO_OFICIAL", ""))
        if derivado:
            _pausar(tel, cfg)
        if textos:
            _anotar_y_avisar(tel, texto, respuesta, derivado, horario, momento, cfg)


_LINKS = re.compile(r"https?://\S+|www\.\S+|wa\.me/\S+", re.IGNORECASE)


def quitar_links(texto: str) -> str:
    """Borra links y deja espacios simples."""
    return re.sub(r"[ \t]{2,}", " ", _LINKS.sub("", texto or "")).strip()


def _pedido_anterior(tel, texto, cfg):
    """si pide "lo mismo de siempre" sin conversación reciente,
    devuelve la pregunta fija con su último pedido anotado (o "")."""
    if not registro_pedidos.pide_repetir(texto):
        return ""
    try:
        ruta = cfg.get("ARCHIVO_PEDIDOS") or os.path.join(RAIZ, registro_pedidos.RUTA_DEFECTO)
        ultimo = registro_pedidos.ultimo_pedido(ruta, tel)
    except Exception:
        return ""
    if not ultimo:
        return ""
    ultimo = " ".join(ultimo.split())[:300]
    return (f"¡Hola de nuevo! Tu último pedido fue: \"{ultimo}\". "
            "¿Quieres lo mismo? Responde sí para confirmar o dime qué cambias.")


def _anotar_y_avisar(tel, texto, respuesta, derivado, horario, momento, cfg):
    """Si falla, el cliente ya recibió su respuesta: solo se avisa en pantalla."""
    try:
        ruta = cfg.get("ARCHIVO_PEDIDOS") or os.path.join(RAIZ, registro_pedidos.RUTA_DEFECTO)
        try:
            registro_pedidos.limpiar_diario(ruta, ahora=momento)
        except Exception:
            pass
        registro_pedidos.anotar(ruta, tel, texto, respuesta, derivado, horario, momento)
    except Exception:
        print("Aviso: no pude anotar el pedido en la lista.", flush=True)
    try:
        avisos.avisar_dueno(avisos.armar_resumen(tel, texto, cfg=cfg), cfg)
    except Exception:
        print("Aviso: no pude avisar al dueño.", flush=True)


def _vaciar_espera(tel, cfg, plantilla):
    with _estado_lock:
        e = _esperas.pop(tel, None)
    if e:
        responder_lote(tel, e["textos"], e["no_texto"], cfg, plantilla)


def recibir_mensaje(m: dict, cfg: dict, plantilla: str):
    tel = m["from"]
    es_texto = m["type"] == "text"
    if en_pausa(tel):
        if es_texto and m["text"].strip().lower() in PALABRAS_REACTIVAR:
            _quitar_pausa(tel)
        else:
            return  # el dueño está atendiendo: el bot no contesta
    espera = float(cfg.get("ESPERA_SEGUNDOS", 0))
    with _estado_lock:
        e = _esperas.setdefault(tel, {"textos": [], "no_texto": False, "timer": None})
        if es_texto:
            e["textos"].append(m["text"])
        else:
            e["no_texto"] = True
        if e["timer"]:
            e["timer"].cancel()
            e["timer"] = None
        if espera > 0:
            e["timer"] = threading.Timer(espera, _vaciar_espera, args=(tel, cfg, plantilla))
            e["timer"].daemon = True
            e["timer"].start()
    if espera <= 0:
        _vaciar_espera(tel, cfg, plantilla)


def procesar_evento(datos: dict, cfg: dict, plantilla: str):
    for m in extraer_mensajes(datos):
        if not m["id"] or not m["from"] or ya_visto(m["id"]):
            continue
        recibir_mensaje(m, cfg, plantilla)


# ---------- servidor ----------
def crear_handler(cfg: dict, plantilla: str):
    class Handler(BaseHTTPRequestHandler):
        def _responder(self, codigo, cuerpo=""):
            datos = cuerpo.encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path != "/webhook":
                return self._responder(404, "no existe")
            self._responder(*verificar_suscripcion(parse_qs(url.query), cfg["META_VERIFY_TOKEN"]))

        def do_POST(self):
            if urlparse(self.path).path != "/webhook":
                return self._responder(404, "no existe")
            try:
                largo = int(self.headers.get("Content-Length") or 0)
                if largo < 0:
                    return self._responder(400, "Content-Length inválido")
            except (ValueError, TypeError):
                return self._responder(400, "Content-Length inválido")
            if largo > 1_000_000:
                return self._responder(413, "muy grande")
            cuerpo = self.rfile.read(largo)
            if not firma_valida(cuerpo, self.headers.get("X-Hub-Signature-256", ""), cfg["META_APP_SECRET"]):
                return self._responder(403, "firma inválida")
            try:
                datos = json.loads(cuerpo or b"{}")
            except ValueError:
                return self._responder(400, "json inválido")
            self._responder(200, "ok")
            threading.Thread(target=procesar_evento, args=(datos, cfg, plantilla), daemon=True).start()

        def log_message(self, *args):  # no registrar URLs (traen el verify token)
            pass

    return Handler


def main():
    leer_env()
    cfg, faltan = cargar_config()
    if faltan:
        print("Falta configurar en el archivo .env: " + ", ".join(faltan))
        print("Copia .env.ejemplo a .env y completa esos datos (ver docs/whatsapp_prueba_pasos.md).")
        return 1
    try:
        plantilla = leer_plantilla(cfg["BOT_PLANTILLA"])
    except OSError:
        print(f"No encontré la plantilla del bot: {cfg['BOT_PLANTILLA']}")
        return 1
    pendientes = datos_sin_llenar(plantilla)
    if pendientes:
        print("El bot todavía tiene datos sin llenar, así que NO lo voy a encender:")
        for p in pendientes:
            print(f"  - {p}")
        print("Escribe el prompt de tu negocio (ver README) y pon en BOT_PLANTILLA")
        print("la ruta de ese archivo .txt o .md.")
        return 1
    registro_pedidos.limpiar_al_arrancar(cfg.get("ARCHIVO_PEDIDOS") or os.path.join(RAIZ, registro_pedidos.RUTA_DEFECTO))
    servidor = ThreadingHTTPServer(("127.0.0.1", cfg["PUERTO"]), crear_handler(cfg, plantilla))
    print(f"Puente listo en http://localhost:{cfg['PUERTO']}/webhook  (Ctrl+C para detener)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nPuente detenido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
