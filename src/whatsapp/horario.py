"""Módulo para saber si el negocio está abierto o cerrado según HORARIO_ATENCION."""
import re
from datetime import datetime, time

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

DIAS = {
    "lun": 0,
    "mar": 1,
    "mie": 2,
    "mié": 2,
    "jue": 3,
    "vie": 4,
    "sab": 5,
    "sáb": 5,
    "dom": 6,
}

PATRON_BLOQUE = re.compile(
    r"^\s*([a-záéíóú]+(?:-[a-záéíóú]+)?)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$",
    re.IGNORECASE,
)


def ahora_chile() -> datetime:
    """Devuelve la hora actual en zona horaria de Chile, o la hora local si falla."""
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("America/Santiago"))
        except Exception:
            pass
    return datetime.now()


def _parsear_hora(s: str) -> time | None:
    try:
        h, m = map(int, s.split(":"))
        return time(h, m)
    except Exception:
        return None


def _parsear_bloque(bloque: str):
    """Devuelve (set_dias, time_inicio, time_fin) o None si es inválido."""
    m = PATRON_BLOQUE.match(bloque.strip())
    if not m:
        return None
    dias_str, ini_str, fin_str = m.group(1).lower(), m.group(2), m.group(3)

    t_ini = _parsear_hora(ini_str)
    t_fin = _parsear_hora(fin_str)
    if t_ini is None or t_fin is None:
        return None

    if "-" in dias_str:
        partes = dias_str.split("-")
        if len(partes) != 2:
            return None
        d1, d2 = partes[0].strip(), partes[1].strip()
        if d1 not in DIAS or d2 not in DIAS:
            return None
        i1, i2 = DIAS[d1], DIAS[d2]
        if i1 <= i2:
            dias = set(range(i1, i2 + 1))
        else:
            dias = set(range(i1, 7)) | set(range(0, i2 + 1))
    else:
        d = dias_str.strip()
        if d not in DIAS:
            return None
        dias = {DIAS[d]}

    return dias, t_ini, t_fin


def estado_horario(ahora: datetime, horario: str) -> str:
    """Devuelve 'abierto', 'cerrado' o 'desconocido' según el horario configurado."""
    if not isinstance(ahora, datetime) or not isinstance(horario, str):
        return "desconocido"
    horario_limpio = horario.strip()
    if not horario_limpio:
        return "desconocido"

    bloques = [b.strip() for b in horario_limpio.split(";") if b.strip()]
    if not bloques:
        return "desconocido"

    bloques_parseados = []
    for b in bloques:
        res = _parsear_bloque(b)
        if res is None:
            return "desconocido"
        bloques_parseados.append(res)

    dia_actual = ahora.weekday()
    hora_actual = ahora.time()

    for dias, t_ini, t_fin in bloques_parseados:
        if dia_actual in dias:
            if t_ini <= t_fin:
                if t_ini <= hora_actual < t_fin:
                    return "abierto"
            else:
                # Horario que cruza la medianoche (ej. 20:00 a 02:00)
                if hora_actual >= t_ini or hora_actual < t_fin:
                    return "abierto"

    return "cerrado"


def linea_contexto(estado: str) -> str:
    """Devuelve la línea de contexto para el prompt del bot según el estado del horario."""
    if estado == "abierto":
        return "(Ahora el negocio está ABIERTO.)"
    if estado == "cerrado":
        return "(Ahora el negocio está CERRADO: toma el pedido y di que se confirma en la mañana.)"
    return ""
