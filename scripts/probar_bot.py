"""Probar el bot de pedidos en la consola (demo local sin WhatsApp ni Meta).

Permite chatear interactivamente con el bot emulando a un cliente de prueba
(teléfono 56900000000) usando las mismas funciones del puente oficial
(memoria, horario de atención, derivación a persona humana, sin enlaces).
"""
import argparse
import json
import os
import sys
import tempfile

# Asegurar que el directorio raíz esté en sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.whatsapp import puente_meta as pm

TEL_PRUEBA = "56900000000"
NEGOCIO_DEFECTO_JSON = os.path.join("evals", "bot_a_pedidos", "negocio_ficticio.json")

_ultima_respuesta: str = ""


def _imprimir_whatsapp(para: str, texto: str, cfg: dict) -> bool:
    """Reemplaza enviar_whatsapp para imprimir en consola en vez de llamar a Meta."""
    global _ultima_respuesta
    _ultima_respuesta = texto
    print(f"\nBot: {texto}\n")
    return True


def obtener_ultima_respuesta() -> str:
    """Devuelve la última respuesta generada por el bot."""
    global _ultima_respuesta
    return _ultima_respuesta


def armar_plantilla(ruta_plantilla: str | None = None) -> tuple[str | None, dict]:
    """Carga y arma la plantilla de system prompt para el bot.

    - Por defecto (None): usa negocio_ficticio.json rellenando la plantilla de pedidos.
    - Si se pasa una ruta a un archivo .json: rellena la plantilla de pedidos con ese JSON.
    - Si se pasa una ruta a un archivo de texto (.txt / .md): lo lee directamente.

    Devuelve (plantilla_texto, dict_negocio) o (None, {}) si el archivo no existe.
    """
    if ruta_plantilla is None:
        ruta_json = os.path.join(ROOT_DIR, NEGOCIO_DEFECTO_JSON)
        if not os.path.exists(ruta_json):
            print(f"No encontré el archivo de negocio por defecto: {ruta_json}")
            return None, {}
        with open(ruta_json, "r", encoding="utf-8") as f:
            negocio = json.load(f)

        plantilla_base = pm.leer_plantilla(pm.PLANTILLA_DEFECTO)
        system_prompt = plantilla_base
        for clave, valor in negocio.items():
            system_prompt = system_prompt.replace(f"{{{clave}}}", str(valor))
        return system_prompt, negocio

    ruta = ruta_plantilla if os.path.isabs(ruta_plantilla) else os.path.join(ROOT_DIR, ruta_plantilla)
    if not os.path.exists(ruta):
        print(f"No encontré la plantilla del bot: {ruta}")
        return None, {}

    if ruta.endswith(".json"):
        with open(ruta, "r", encoding="utf-8") as f:
            negocio = json.load(f)
        plantilla_base = pm.leer_plantilla(pm.PLANTILLA_DEFECTO)
        system_prompt = plantilla_base
        for clave, valor in negocio.items():
            system_prompt = system_prompt.replace(f"{{{clave}}}", str(valor))
        return system_prompt, negocio
    else:
        plantilla = pm.leer_plantilla(ruta)
        return plantilla, {}


def verificar_plantilla(plantilla: str | None) -> bool:
    """Verifica si la plantilla tiene marcadores sin llenar o advertencias.

    Si faltan datos, imprime el aviso en español simple (igual que el puente) y retorna False.
    """
    if plantilla is None:
        return False
    pendientes = pm.datos_sin_llenar(plantilla)
    if pendientes:
        print("El bot todavía tiene datos sin llenar, así que NO lo voy a encender:")
        for p in pendientes:
            print(f"  - {p}")
        return False
    return True


def configurar_puente_consola(negocio: dict | None = None, archivo_pedidos: str | None = None) -> dict:
    """Configura el puente para operar en modo consola local sin WhatsApp ni Meta."""
    pm.leer_env()
    cfg, _ = pm.cargar_config()

    # Ajustes para modo interactivo de consola
    cfg["ESPERA_SEGUNDOS"] = 0
    cfg["CANAL_AVISO"] = "ninguno"

    # Redirigir archivo de pedidos a un archivo temporal para nunca tocar outputs/pedidos/pedidos.csv
    if archivo_pedidos is None:
        archivo_pedidos = os.path.join(tempfile.gettempdir(), "pedidos_demo.csv")
    cfg["ARCHIVO_PEDIDOS"] = archivo_pedidos

    # Configuración de teléfono y horario si vienen del negocio ficticio
    if negocio:
        if not cfg.get("TELEFONO_OFICIAL") and negocio.get("TELEFONO_OFICIAL"):
            cfg["TELEFONO_OFICIAL"] = negocio["TELEFONO_OFICIAL"]
        if not cfg.get("HORARIO_ATENCION"):
            horario_txt = negocio.get("HORARIOS_ATENCION", "")
            if "09:00" in horario_txt:
                cfg["HORARIO_ATENCION"] = "lun-vie 09:00-19:00; sab 10:00-14:00"
            else:
                cfg["HORARIO_ATENCION"] = horario_txt

    # Reemplazar envío a WhatsApp para que imprima en consola
    pm.enviar_whatsapp = _imprimir_whatsapp
    # Silenciar logs del servidor para una experiencia limpia de chat
    pm.registrar = lambda *a, **k: None

    return cfg


def procesar_linea(linea: str, cfg: dict, plantilla: str, tel: str = TEL_PRUEBA) -> str | None:
    """Procesa un mensaje del usuario simulando el flujo de WhatsApp.

    Respeta pausas si el bot derivó a una persona, historial y horarios.
    """
    global _ultima_respuesta
    _ultima_respuesta = ""

    texto = linea.strip()
    if not texto:
        return None

    if pm.en_pausa(tel):
        if texto.lower() in pm.PALABRAS_REACTIVAR:
            pm._quitar_pausa(tel)
        else:
            print("[El bot está en pausa porque te derivó con una persona. Escribe 'menú' para reactivarlo.]")
            return None

    pm.responder_lote(tel, [texto], False, cfg, plantilla)
    return _ultima_respuesta


def chat_interactivo(cfg: dict, plantilla: str, negocio: dict | None = None, lector_input=None) -> None:
    """Bucle principal de conversación en consola."""
    if lector_input is None:
        lector_input = input

    nombre_negocio = (negocio or {}).get("NOMBRE_NEGOCIO")
    if not nombre_negocio:
        import re
        m = re.search(r'Asistente Virtual Oficial de "([^"]+)"', plantilla or "")
        nombre_negocio = m.group(1) if m else "Bot de Pedidos"
    print("=" * 60)
    print("--- Probador del Bot de Pedidos (Demo Local sin WhatsApp) ---")
    print(f"Negocio: {nombre_negocio}")
    print(f"Teléfono de prueba: {TEL_PRUEBA}")
    print("Escribe un mensaje para conversar con el bot.")
    print("Escribe 'salir' para terminar.")
    print("=" * 60)

    while True:
        try:
            entrada = lector_input("Tú: ")
        except (EOFError, KeyboardInterrupt):
            print("\nConversación finalizada.")
            break

        texto = entrada.strip()
        if not texto:
            continue
        if texto.lower() == "salir":
            print("Conversación finalizada.")
            break

        procesar_linea(texto, cfg, plantilla)


def main(argv: list[str] | None = None, lector_input=None) -> int:
    parser = argparse.ArgumentParser(
        description="Probador del bot de pedidos en la consola (sin WhatsApp)"
    )
    parser.add_argument(
        "--plantilla",
        default=None,
        help="Ruta a la plantilla (.txt, .md o .json con datos del negocio)"
    )
    args = parser.parse_args(argv)

    plantilla, negocio = armar_plantilla(args.plantilla)
    if not verificar_plantilla(plantilla):
        return 1

    cfg = configurar_puente_consola(negocio=negocio)
    pm.limpiar_estado()
    chat_interactivo(cfg, plantilla, negocio, lector_input=lector_input)
    return 0


if __name__ == "__main__":
    sys.exit(main())
