"""Punto único para avisar al dueño de un pedido nuevo o solicitud de atención.

Canales disponibles:
- ninguno: canal apagado por defecto.
- telegram: envía el aviso al chat de Telegram del dueño usando la API oficial (gratis).
"""
import json
import os
import re
import urllib.error
import urllib.request

_RE_PIDE_PERSONA = re.compile(
    r"\b(hablar|habla|comunicar|contactar|atender|atienda|pasa|p[aá]same|p[aá]sa me)\b.*"
    r"\b(persona|humano|alguien|due[nñ]o|due[nñ]a|encargad[oa]|ejecutiv[oa])\b"
    r"|\b(atender|atienda|atiende)\s+alguien\b"
    r"|\bpide\s+hablar\s+con\s+una\s+persona\b",
    re.IGNORECASE,
)


def armar_resumen(
    telefono: str,
    texto_cliente: str,
    tipo: str | None = None,
    hora: str | None = None,
    fuera_horario: bool | str = False,
    sin_texto: bool | None = None,
    cfg: dict | None = None,
) -> str:
    """Resumen corto sin el número completo del cliente para avisar al dueño."""
    if sin_texto is None:
        cfg = cfg or {}
        val = cfg.get("AVISO_SIN_TEXTO") or os.environ.get("AVISO_SIN_TEXTO") or ""
        sin_texto = str(val).strip() in ("1", "true", "True", "si", "SI")

    tel_corto = f"...{(telefono or '')[-4:]}"

    if tipo:
        tipo_final = "Pide hablar con una persona" if "persona" in tipo.lower() else tipo
    else:
        tipo_final = (
            "Pide hablar con una persona"
            if _RE_PIDE_PERSONA.search(texto_cliente or "")
            else "Pedido nuevo"
        )

    if sin_texto:
        return f"{tipo_final} de {tel_corto}, revisa la lista"

    texto = " ".join((texto_cliente or "").split())[:300]

    detalles = []
    if hora:
        detalles.append(str(hora).strip())
    if fuera_horario:
        if isinstance(fuera_horario, str) and fuera_horario.strip():
            detalles.append(fuera_horario.strip())
        else:
            detalles.append("de noche, fuera de horario")

    extra = f" ({', '.join(detalles)})" if detalles else ""
    return f"{tipo_final}{extra} {tel_corto}: {texto}"


def avisar_dueno(resumen: str, cfg: dict | None = None) -> bool:
    """Devuelve True solo si el aviso se envió correctamente al dueño."""
    cfg = cfg or {}
    canal = (cfg.get("CANAL_AVISO") or os.environ.get("CANAL_AVISO") or "ninguno").strip().lower()
    if canal == "ninguno":
        return False

    if canal == "telegram":
        token = (cfg.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or "").strip()
        chat_id = (cfg.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
        if not token or not chat_id:
            print("Aviso: falta configurar TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en .env o entorno.", flush=True)
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": str(chat_id), "text": resumen}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                codigo = getattr(resp, "status", None)
                if codigo is None:
                    codigo = resp.getcode()
                if 200 <= codigo < 300:
                    return True
                print(f"Aviso: Telegram respondió con código {codigo}.", flush=True)
                return False
        except Exception:
            # NO imprimir la excepción: trae el token
            print("Aviso: no pude enviar el aviso por Telegram (falló la conexión o la API).", flush=True)
            return False

    print(f"Canal de aviso '{canal}' aún no está hecho", flush=True)
    return False
