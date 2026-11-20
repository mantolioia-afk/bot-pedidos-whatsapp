"""
Script evaluador para bots de WhatsApp con revisiones deterministas automáticas
y juez evaluador IA (Ollama local).
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime
from typing import Dict, Any, Optional

# Asegurar que el directorio raíz esté en sys.path para importaciones
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.core.llm_router import call_ollama


def extraer_respuesta_json(raw_text: Optional[str]) -> Optional[str]:
    """Extrae el texto de la respuesta del JSON devuelto por Ollama."""
    if not raw_text:
        return None

    texto = raw_text.strip()

    # 1. Intento directo
    try:
        data = json.loads(texto)
        if isinstance(data, dict):
            val = data.get("respuesta") or data.get("response")
            if val and isinstance(val, str):
                return val.strip()
    except Exception:
        pass

    # 2. Quitar bloques markdown ```json ... ```
    texto_sin_bloques = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.MULTILINE)
    texto_sin_bloques = re.sub(r"\s*```$", "", texto_sin_bloques.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(texto_sin_bloques)
        if isinstance(data, dict):
            val = data.get("respuesta") or data.get("response")
            if val and isinstance(val, str):
                return val.strip()
    except Exception:
        pass

    # 3. Buscar el primer objeto JSON {...}
    match = re.search(r"\{.*?\}", texto, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                val = data.get("respuesta") or data.get("response")
                if val and isinstance(val, str):
                    return val.strip()
        except Exception:
            pass

    return None


def _cargar_json_flexible(raw_text: Optional[str]) -> Optional[dict]:
    """Intenta leer un objeto JSON (aunque venga con ```json o texto alrededor)."""
    if not raw_text:
        return None
    texto = raw_text.strip()
    candidatos = [texto]
    sin_bloques = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.MULTILINE)
    candidatos.append(re.sub(r"\s*```$", "", sin_bloques.strip(), flags=re.MULTILINE))
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if m:
        candidatos.append(m.group(0))
    for c in candidatos:
        try:
            data = json.loads(c)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


# Bot B y Bot C no son conversaciones de WhatsApp: su molde exige una salida con
# estructura (campos de la factura / categoría del correo). Para medirlos bien,
# el evaluador les pide ese formato. El Bot A (y cualquier otra carpeta) sigue igual.
PEDIDO_POR_DEFECTO = 'Responde en JSON con la forma {"respuesta": "texto que enviarías por WhatsApp"}'
PEDIDOS_POR_BOT = {
    "bot_b": (
        'Responde en JSON con la forma {"campos": {"fecha_emision": "...", "rut_emisor": "...", '
        '"razon_social_emisor": "...", "folio": "...", "monto_neto_clp": 0, "monto_iva_clp": 0, '
        '"monto_total_clp": 0, "alerta_discrepancia_iva": false}, '
        '"respuesta": "mensaje breve para el usuario"}. Si un dato no viene en el mensaje, déjalo vacío.'
    ),
    "bot_c": (
        'Responde en JSON con la forma {"categoria": "URGENTE | COTIZACION_NUEVA | CONSULTA_GENERAL | '
        'SPAM_O_INFORMATIVO (elige solo una)", "respuesta": "borrador de respuesta al correo (vacío si es spam)"}'
    ),
}


def pedido_formato(prefijo: str) -> str:
    """Instrucción de formato que se agrega al mensaje del cliente según el bot."""
    return PEDIDOS_POR_BOT.get(prefijo, PEDIDO_POR_DEFECTO)


def extraer_salida_bot(raw_text: Optional[str], prefijo: str) -> Optional[str]:
    """
    Convierte la salida del bot en el texto que se revisa.
    - bot_a / otros: igual que siempre (extraer_respuesta_json).
    - bot_b: respuesta + campos extraídos (la alerta de IVA solo aparece si es true).
    - bot_c: 'CATEGORIA: X' + borrador.
    """
    if prefijo not in PEDIDOS_POR_BOT:
        return extraer_respuesta_json(raw_text)

    data = _cargar_json_flexible(raw_text)
    if data is None:
        return None
    respuesta = data.get("respuesta") or data.get("response") or ""
    if not isinstance(respuesta, str):
        respuesta = json.dumps(respuesta, ensure_ascii=False)
    respuesta = respuesta.strip()

    if prefijo == "bot_c":
        categoria = data.get("categoria") or data.get("category")
        if not isinstance(categoria, str) or not categoria.strip():
            return respuesta or None
        return f"CATEGORIA: {categoria.strip()}\n\n{respuesta}".strip()

    # bot_b
    campos = data.get("campos")
    lineas = []
    if isinstance(campos, dict):
        for k, v in campos.items():
            if k == "alerta_discrepancia_iva":
                if v is True or str(v).strip().lower() == "true":
                    lineas.append("alerta_discrepancia_iva: true")
                continue
            if v not in (None, "", 0):
                lineas.append(f"{k}: {v}")
    if not respuesta and not lineas:
        return None
    return "\n".join([respuesta] + lineas).strip()


def parsear_evaluacion_juez(raw_text: Optional[str]) -> Dict[str, Any]:
    """
    Parsea y valida la respuesta del juez IA.
    Si la nota no es un número entre 1.0 y 7.0, guarda null (None en Python).
    """
    if not raw_text:
        return {"nota": None, "motivo": None}

    texto = raw_text.strip()
    data = None

    try:
        data = json.loads(texto)
    except Exception:
        texto_sin_bloques = re.sub(r"^```(?:json)?\s*", "", texto, flags=re.MULTILINE)
        texto_sin_bloques = re.sub(r"\s*```$", "", texto_sin_bloques.strip(), flags=re.MULTILINE)
        try:
            data = json.loads(texto_sin_bloques)
        except Exception:
            m = re.search(r"\{.*?\}", texto, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    pass

    if not isinstance(data, dict):
        return {"nota": None, "motivo": None}

    raw_nota = data.get("nota")
    motivo = data.get("motivo")
    if motivo is not None:
        motivo = str(motivo).strip()

    nota_valida = None
    if raw_nota is not None:
        try:
            if isinstance(raw_nota, str):
                raw_nota = raw_nota.replace(",", ".").strip()
            val = float(raw_nota)
            if 1.0 <= val <= 7.0:
                nota_valida = round(val, 2)
        except (ValueError, TypeError):
            nota_valida = None

    return {"nota": nota_valida, "motivo": motivo}


def evaluar_con_juez(mensaje_cliente: str, respuesta_bot: str) -> Dict[str, Any]:
    """
    Llama a Ollama actuando como evaluador estricto (nota de 1.0 a 7.0 y motivo).
    Juzga:
    1. Tono chileno cordial.
    2. Que responda lo que el cliente preguntó.
    3. Que no invente datos.
    """
    system_juez = (
        "Eres un evaluador y juez estricto de calidad de atención al cliente por WhatsApp en Chile. "
        "Evalúas la respuesta que un bot le dio a un cliente. "
        "Criterios de evaluación (escala chilena de notas 1.0 a 7.0):\n"
        "- Tono chileno cordial y profesional.\n"
        "- Que responda directamente lo que el cliente preguntó o necesita.\n"
        "- Que no invente datos, precios falsos o información no autorizada.\n"
        "Debes responder ÚNICAMENTE en JSON con este formato exacto:\n"
        '{"nota": 5.5, "motivo": "una frase explicando la calificación"}'
    )

    prompt_juez = (
        f"Mensaje del cliente: {mensaje_cliente}\n\n"
        f"Respuesta del bot: {respuesta_bot}\n\n"
        "Evalúa la respuesta del bot y devuelve el JSON con 'nota' (número de 1.0 a 7.0) y 'motivo'."
    )

    raw_resp = call_ollama(prompt=prompt_juez, system_prompt=system_juez)
    return parsear_evaluacion_juez(raw_resp)


def revisar_respuesta(respuesta: str, debe_cumplir: list, negocio: dict) -> dict:
    """
    Evalúa una respuesta frente a directrices y etiquetas obligatorias:
    - Siempre: sin enlaces (expresión regular oficial de st4_deterministic_guards).
    - muestra_menu: aparecen '1', '2', '3' y '4' como opciones numeradas.
    - deriva_humano: aparece el teléfono del negocio ficticio o la palabra 'recepción'.
    - rechaza_fuera_horario: no confirma la cita y menciona el horario.
    - no_inventa_precio / precio_en_clp: si aparece un monto con '$', debe decir 'CLP'.
    """
    texto = respuesta or ""
    pasaron = []
    fallaron = []
    detalles = {}

    # 1. Siempre: sin enlaces (misma regex de check_revisor_1_seguridad)
    url_pattern = r"(https?://|www\.|\.cl\b|\.com\b|\.net\b|wa\.me|t\.me|bit\.ly|tinyurl\.com|@)"
    tiene_enlace = bool(re.search(url_pattern, texto, re.IGNORECASE))
    if tiene_enlace:
        fallaron.append("sin_enlaces")
        detalles["sin_enlaces"] = False
    else:
        pasaron.append("sin_enlaces")
        detalles["sin_enlaces"] = True

    # 2. Revisión de etiquetas solicitadas en debe_cumplir
    # Algunas etiquetas (Bot B / Bot C) llevan un valor esperado: "nombre:valor"
    for etiqueta in debe_cumplir:
        nombre, _, valor = etiqueta.partition(":")
        if nombre == "extrae_monto" and valor:
            # el monto esperado aparece en la respuesta (acepta 119.000, 119,000 o 119000)
            numeros = [re.sub(r"[.,]", "", n) for n in re.findall(r"\d[\d.,]*\d|\d", texto)]
            ok = re.sub(r"\D", "", valor) in numeros
        elif nombre == "extrae_rut" and valor:
            # el RUT esperado aparece (sin importar puntos, guion ni mayúsculas)
            limpio = lambda s: re.sub(r"[^0-9K]", "", s.upper())
            ok = limpio(valor) != "" and limpio(valor) in limpio(texto)
        elif nombre == "clasifica_categoria" and valor:
            # aparece la categoría esperada y ninguna de las otras
            categorias = ["URGENTE", "COTIZACION_NUEVA", "CONSULTA_GENERAL", "SPAM_O_INFORMATIVO"]
            mayus = texto.upper()
            presentes = [c for c in categorias if re.search(rf"\b{c}\b", mayus)]
            ok = presentes == [valor.upper()]
        elif etiqueta == "alerta_iva":
            # marca la discrepancia de IVA
            ok = bool(re.search(r"alerta_discrepancia_iva\W*\s*(?:=|:)?\s*true|discrepancia|no\s+cuadra|no\s+coincide", texto, re.IGNORECASE))
        elif etiqueta == "muestra_menu":
            # aparecen "1", "2", "3" y "4" como opciones numeradas
            ok = all(
                bool(re.search(rf"(?:^|[\n\s\(\[\*])(?:\*)?0?{d}(?:\*)?\s*[\.\)\-\:\]](?:\*|\s|[a-zA-ZáéíóúÁÉÍÓÚñÑ]|$)", texto))
                for d in ["1", "2", "3", "4"]
            )
        elif etiqueta == "deriva_humano":
            # aparece el teléfono del negocio ficticio o la palabra "recepción"
            tel = negocio.get("TELEFONO_OFICIAL", "") if negocio else ""
            tel_digitos = re.sub(r"\D", "", tel)
            resp_digitos = re.sub(r"\D", "", texto)
            tel_en_resp = (tel != "" and tel in texto) or (len(tel_digitos) >= 8 and tel_digitos[-8:] in resp_digitos)
            palabra_recepcion = bool(re.search(r"recepci[oó]n", texto, re.IGNORECASE))
            ok = tel_en_resp or palabra_recepcion
        elif etiqueta == "rechaza_fuera_horario":
            # no confirma la cita y menciona el horario
            patron_confirma = (
                r"(?:cita|hora|reserva)\s+(?:ha sido\s+)?confirmada|"
                r"te\s+confirmo\s+(?:la\s+)?(?:cita|hora|reserva)|"
                r"qued[oó]\s+(?:agendad[ao]|confirmad[ao])|"
                r"te\s+esperamos\s+(?:el|este|hoy)|"
                r"agendad[ao]\s+con\s+[eé]xito|"
                r"agendad[ao]\s+para\s+(?:el|este|hoy|\d)"
            )
            confirma = bool(re.search(patron_confirma, texto, re.IGNORECASE))
            menciona_horario = bool(re.search(r"\bhorarios?\b|\blunes\b|\bviernes\b|\bs[aá]bado\b|\b0?9:00\b|\b19:00\b|\b10:00\b|\b14:00\b", texto, re.IGNORECASE))
            ok = (not confirma) and menciona_horario
        elif etiqueta == "confirma_en_manana":
            # de noche: dice que se confirma en la mañana y no da el pedido por confirmado
            dice_manana = bool(re.search(r"ma[ñn]ana", texto, re.IGNORECASE))
            ya_confirmado = bool(re.search(r"pedido\s+(?:est[aá]\s+|qued[oó]\s+)?confirmado|ya\s+est[aá]\s+listo", texto, re.IGNORECASE))
            ok = dice_manana and not ya_confirmado
        elif etiqueta == "pregunta_producto":
            # no adivina: pregunta qué producto o cuánto
            ok = "?" in texto and bool(re.search(r"producto|cantidad|cu[aá]nt[oa]s?|qu[eé]\s+(?:necesitas|quieres|te\s+llevamos)", texto, re.IGNORECASE))
        elif etiqueta in ["no_inventa_precio", "precio_en_clp"]:
            # si aparece un monto con "$", debe decir "CLP"
            if "$" in texto:
                ok = bool(re.search(r"\bCLP\b", texto, re.IGNORECASE))
            else:
                ok = True
        else:
            ok = False

        detalles[etiqueta] = ok
        if ok:
            pasaron.append(etiqueta)
        else:
            fallaron.append(etiqueta)

    aprobado = (len(fallaron) == 0)

    return {
        "aprobado": aprobado,
        "pasaron": pasaron,
        "fallaron": fallaron,
        "detalles": detalles,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluador de bots con revisiones deterministas automáticas")
    parser.add_argument(
        "--plantilla",
        default="brain/moldes_maestros/bot_a_pedidos/system_prompt_template.md",
        help="Ruta a la plantilla del system prompt"
    )
    parser.add_argument(
        "--carpeta",
        default="evals/bot_a_pedidos",
        help="Carpeta con negocio_ficticio.json y casos.json"
    )
    parser.add_argument(
        "--juez",
        action="store_true",
        default=False,
        help="Activa el juez IA (Ollama) para calificar cada respuesta con nota de 1.0 a 7.0"
    )

    parser.add_argument(
        "--modelo",
        default=None,
        help="Modelo de Ollama a usar (ej: qwen3:4b). Por defecto, el mismo que usa la fábrica (llama3.2)."
    )

    args = parser.parse_args()

    plantilla_path = args.plantilla
    if not os.path.isabs(plantilla_path):
        plantilla_path = os.path.join(ROOT_DIR, plantilla_path)

    carpeta_path = args.carpeta
    if not os.path.isabs(carpeta_path):
        carpeta_path = os.path.join(ROOT_DIR, carpeta_path)

    if not os.path.exists(plantilla_path):
        print(f"Error: No existe el archivo de plantilla en {plantilla_path}")
        sys.exit(1)

    negocio_file = os.path.join(carpeta_path, "negocio_ficticio.json")
    if not os.path.exists(negocio_file):
        print(f"Error: No existe {negocio_file}")
        sys.exit(1)

    casos_file = os.path.join(carpeta_path, "casos.json")
    if not os.path.exists(casos_file):
        print(f"Error: No existe {casos_file}")
        sys.exit(1)

    with open(plantilla_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    with open(negocio_file, "r", encoding="utf-8") as f:
        negocio = json.load(f)

    with open(casos_file, "r", encoding="utf-8") as f:
        casos = json.load(f)

    # Rellenar plantilla sin .format() usando .replace("{CLAVE}", valor)
    system_prompt = prompt_template
    for clave, valor in negocio.items():
        system_prompt = system_prompt.replace(f"{{{clave}}}", str(valor))

    prefijo_bot = os.path.basename(os.path.normpath(carpeta_path))

    total = len(casos)
    aprobados = 0
    fallados = 0
    errores = 0
    resultados_casos = []

    print("=" * 60)
    print(f"Iniciando evaluación de {total} casos...")
    print(f"Plantilla: {plantilla_path}")
    print(f"Negocio: {negocio.get('NOMBRE_NEGOCIO', 'Desconocido')}")
    print(f"Juez IA: {'ACTIVADO' if args.juez else 'DESACTIVADO'}")
    print("=" * 60)

    for i, caso in enumerate(casos, 1):
        caso_id = caso.get("id", f"C{i:02d}")
        tipo = caso.get("tipo", "desconocido")
        mensaje = caso.get("mensaje_cliente", "")
        debe_cumplir = caso.get("debe_cumplir", [])

        prompt = f"{mensaje}\n\n{pedido_formato(prefijo_bot)}"

        raw_resp = call_ollama(prompt=prompt, system_prompt=system_prompt, model=args.modelo, timeout=120)
        respuesta_texto = extraer_salida_bot(raw_resp, prefijo_bot)

        if respuesta_texto is None:
            errores += 1
            fallados += 1
            juez_eval = {"nota": None, "motivo": "Sin respuesta válida del bot"} if args.juez else None
            resultado_caso = {
                "id": caso_id,
                "tipo": tipo,
                "mensaje_cliente": mensaje,
                "debe_cumplir": debe_cumplir,
                "respuesta": None,
                "raw_response": raw_resp,
                "estado": "error",
                "error": "Ollama no respondió o el JSON no tiene el campo 'respuesta'",
                "aprobado": False,
                "pasaron": [],
                "fallaron": ["error_json_o_llm"] + debe_cumplir,
                "detalles": {},
                "juez": juez_eval
            }
            print(f"[{i:02d}/{total:02d}] {caso_id} ({tipo}): ERROR (Sin respuesta válida de Ollama)")
        else:
            rev = revisar_respuesta(respuesta_texto, debe_cumplir, negocio)
            juez_eval = None
            if args.juez:
                juez_eval = evaluar_con_juez(mensaje, respuesta_texto)

            if rev["aprobado"]:
                aprobados += 1
                estado = "aprobado"
                msg_consola = f"[{i:02d}/{total:02d}] {caso_id} ({tipo}): APROBADO"
            else:
                fallados += 1
                estado = "fallado"
                msg_consola = f"[{i:02d}/{total:02d}] {caso_id} ({tipo}): FALLADO -> Fallaron: {', '.join(rev['fallaron'])}"

            if args.juez and juez_eval:
                nota_display = f"{juez_eval['nota']}" if juez_eval["nota"] is not None else "null"
                msg_consola += f" | Juez: Nota {nota_display}/7.0 ({juez_eval.get('motivo') or 'sin motivo'})"

            print(msg_consola)

            resultado_caso = {
                "id": caso_id,
                "tipo": tipo,
                "mensaje_cliente": mensaje,
                "debe_cumplir": debe_cumplir,
                "respuesta": respuesta_texto,
                "estado": estado,
                "aprobado": rev["aprobado"],
                "pasaron": rev["pasaron"],
                "fallaron": rev["fallaron"],
                "detalles": rev["detalles"],
                "juez": juez_eval
            }

        resultados_casos.append(resultado_caso)

    outputs_dir = os.path.join(ROOT_DIR, "outputs", "evals")
    os.makedirs(outputs_dir, exist_ok=True)

    prefijo = os.path.basename(os.path.normpath(carpeta_path)) or "bot_a"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_filename = f"{prefijo}_{timestamp}.json"
    output_path = os.path.join(outputs_dir, output_filename)

    if os.path.exists(output_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{prefijo}_{timestamp}.json"
        output_path = os.path.join(outputs_dir, output_filename)

    porcentaje = (aprobados / total * 100.0) if total > 0 else 0.0

    notas_juez = [
        c["juez"]["nota"] for c in resultados_casos
        if c.get("juez") and c["juez"].get("nota") is not None
    ]
    nota_promedio = round(sum(notas_juez) / len(notas_juez), 2) if notas_juez else None

    resumen_data = {
        "total": total,
        "aprobados": aprobados,
        "fallados": fallados,
        "errores": errores,
        "porcentaje_aprobacion": round(porcentaje, 2)
    }
    if args.juez:
        resumen_data["nota_promedio"] = nota_promedio

    eval_data = {
        "timestamp": datetime.now().isoformat(),
        "plantilla": args.plantilla,
        "carpeta": args.carpeta,
        "juez_habilitado": args.juez,
        "resumen": resumen_data,
        "casos": resultados_casos
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(eval_data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("RESUMEN DE EVALUACIÓN")
    print("=" * 60)
    print(f"Total de casos: {total}")
    print(f"Casos aprobados: {aprobados}")
    print(f"Casos fallados: {fallados}")
    print(f"Errores de inferencia / JSON: {errores}")
    print(f"Porcentaje de aprobación: {porcentaje:.2f}%")
    if args.juez:
        if nota_promedio is not None:
            print(f"Nota promedio juez IA: {nota_promedio:.2f} / 7.0 ({len(notas_juez)}/{total} notas válidas)")
        else:
            print("Nota promedio juez IA: Sin notas válidas (null)")
    print(f"Archivo guardado: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
