"""lista de pedidos en el PC (CSV que se abre en Excel).

Cada lote de mensajes de un cliente queda como una fila con estado "pendiente".
El dueño cambia el estado a mano. El bot nunca confirma pedidos.
"""
import csv
import os
import re
import threading
from datetime import datetime

RUTA_DEFECTO = os.path.join("outputs", "pedidos", "pedidos.csv")
ENCABEZADO = ["fecha", "telefono", "mensaje_cliente", "respuesta_bot",
              "derivado_a_persona", "horario", "estado"]

_lock = threading.RLock()
_ultima_limpieza: dict[str, datetime] = {}
INTERVALO_LIMPIEZA_HORAS = 24

_CARACTERES_FORMULA = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitizar_celda(valor, es_telefono: bool = False) -> str:
    """evita inyección de fórmulas en Excel anteponiendo una comilla simple (').

    Si el texto empieza con '=', '+', '-', '@', tabulador o retorno, se le antepone comilla simple.
    La columna teléfono se exceptúa si empieza con '+' (formato internacional E.164),
    pero sí se protege si empieza con '=', '-', '@' u otros.
    """
    if valor is None:
        return ""
    texto = str(valor)
    if not texto:
        return ""
    if es_telefono and texto.startswith("+"):
        return texto
    if texto.startswith(_CARACTERES_FORMULA):
        return "'" + texto
    return texto


def anotar(ruta: str, telefono: str, texto_cliente: str, respuesta_bot: str,
           derivado: bool, estado_horario: str, momento: datetime) -> None:
    """Agrega una fila al CSV (lo crea con encabezado si no existe)."""
    carpeta = os.path.dirname(ruta)
    with _lock:
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        nuevo = not os.path.exists(ruta) or os.path.getsize(ruta) == 0
        # utf-8-sig: BOM al inicio para que Excel muestre bien las tildes
        with open(ruta, "a", newline="", encoding="utf-8-sig" if nuevo else "utf-8") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(ENCABEZADO)
            w.writerow([
                momento.strftime("%Y-%m-%d %H:%M"),
                sanitizar_celda(telefono, es_telefono=True),
                sanitizar_celda(texto_cliente),
                sanitizar_celda(respuesta_bot),
                "si" if derivado else "no",
                sanitizar_celda(estado_horario),
                "pendiente",
            ])


FORMATO_FECHA = "%Y-%m-%d %H:%M"
DIAS_DEFECTO = 90


def _dias_env() -> int:
    try:
        dias = int(os.environ.get("DIAS_GUARDAR_PEDIDOS") or DIAS_DEFECTO)
        return dias if dias > 0 else DIAS_DEFECTO
    except ValueError:
        return DIAS_DEFECTO


def limpiar_viejos(ruta: str, dias: int = None, ahora: datetime = None) -> int:
    """borra los pedidos de hace más de `dias` días (datos personales).

    `dias` por defecto sale de DIAS_GUARDAR_PEDIDOS en .env (90 si no está).
    El encabezado y las filas rotas (fecha ilegible) se conservan.
    Escribe a un archivo temporal y luego lo reemplaza (no deja el CSV a medias).
    Devuelve cuántas filas borró.

    Ojo: "lo mismo de siempre" solo podrá recordar pedidos que sigan
    dentro de esos días; los más viejos ya no existen.
    """
    if dias is None:
        dias = _dias_env()
    ahora = ahora or datetime.now()
    with _lock:
        ruta_abs = os.path.abspath(ruta)
        _ultima_limpieza[ruta_abs] = ahora
        if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
            return 0
        # utf-8-sig lee bien con o sin BOM
        with open(ruta, newline="", encoding="utf-8-sig") as f:
            filas = list(csv.reader(f))
        quedan, borradas = [], 0
        for i, fila in enumerate(filas):
            if i > 0 and fila:
                try:
                    fecha = datetime.strptime(fila[0], FORMATO_FECHA)
                except (ValueError, IndexError):
                    fecha = None
                if fecha is not None and (ahora - fecha).days > dias:
                    borradas += 1
                    continue
            quedan.append(fila)
        if borradas == 0:
            return 0
        temporal = ruta + ".tmp"
        with open(temporal, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(quedan)
        os.replace(temporal, ruta)
        return borradas


def limpiar_diario(ruta: str = None, ahora: datetime = None) -> int:
    """ejecuta limpiar_viejos como máximo una vez cada 24 horas mientras el puente sigue prendido.

    Devuelve la cantidad de filas borradas (0 si no tocaba limpiar o no se borró nada).
    """
    ruta = ruta or RUTA_DEFECTO
    ahora = ahora or datetime.now()
    ruta_abs = os.path.abspath(ruta)
    with _lock:
        ultima = _ultima_limpieza.get(ruta_abs)
        if ultima is not None and 0 <= (ahora - ultima).total_seconds() < INTERVALO_LIMPIEZA_HORAS * 3600:
            return 0
        return limpiar_viejos(ruta, ahora=ahora)


_SALUDOS = {"hola", "holi", "buenas", "buenos dias", "buenas tardes", "buenas noches",
            "menu", "gracias", "ok", "si", "no"}


def _normalizar(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


_REPETIR = re.compile(r"\blo (mismo|de) (de )?siempre\b|\blo mismo que (la otra vez|la vez pasada|antes)\b"
                      r"|\brepetir (el |mi )?pedido\b")


def pide_repetir(texto: str) -> bool:
    """True si el cliente pide repetir su pedido ("lo mismo de siempre", etc.)."""
    return bool(_REPETIR.search(_normalizar(texto)))


def ultimo_pedido(ruta: str, telefono: str):
    """último mensaje_cliente de ese teléfono que sea un pedido de verdad.

    Ignora saludos y los "lo mismo de siempre". Devuelve None si no hay.
    Nunca se cae: archivo vacío, inexistente o filas rotas → None / se saltan.
    """
    try:
        with _lock:
            if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
                return None
            with open(ruta, newline="", encoding="utf-8-sig") as f:
                filas = list(csv.reader(f))
    except Exception:
        return None
    for fila in reversed(filas[1:]):
        if len(fila) < 3:
            continue
        tel_fila = fila[1].lstrip("'")
        tel_buscar = telefono.lstrip("'") if isinstance(telefono, str) else str(telefono)
        if tel_fila != tel_buscar and fila[1] != telefono:
            continue
        texto = (fila[2] or "").strip()
        if texto[:1] == "'" and texto[1:2] and texto[1:2] in "=+-@":
            texto = texto[1:]  # quitar la comilla de protección
        norm = _normalizar(texto)
        if not norm or norm in _SALUDOS or pide_repetir(texto):
            continue
        return texto
    return None


def limpiar_al_arrancar(ruta: str) -> None:
    """Llama a limpiar_viejos sin dejar caer el bot si algo falla.

    Borra el archivo temporal .tmp si quedó de una caída o corte anterior.
    """
    try:
        tmp = ruta + ".tmp"
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        n = limpiar_viejos(ruta)
        if n:
            print(f"Borré {n} pedidos antiguos de la lista (privacidad).", flush=True)
    except Exception:
        print("Aviso: no pude limpiar los pedidos antiguos de la lista.", flush=True)
