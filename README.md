# Bot de pedidos por WhatsApp / WhatsApp order bot

*[Español](#español) · [English](#english)*

---

## Español

Bot para que **negocios pequeños** (reparto de agua, almacenes, distribuidoras, bazares) atiendan pedidos por WhatsApp automáticamente. Funciona con **IA local y gratis** (Ollama) en un PC normal: sin pagar servicios de IA en la nube.

### Qué hace
- Responde a los clientes con los precios, zonas y horarios del negocio.
- Toma el pedido y lo anota en una lista (CSV que se abre en Excel).
- Avisa al dueño en su celular por Telegram (opcional).
- Si el cliente pide hablar con una persona, le da el teléfono del dueño y se queda callado con ese cliente hasta que escriba "menú".
- Fuera de horario, avisa que el pedido se atiende al día siguiente.
- "Lo mismo de siempre": recuerda el último pedido del cliente.

### Seguridad incluida
- Filtro sin IA que bloquea respuestas con precios o descuentos inventados.
- Verifica la firma de Meta (`X-Hub-Signature-256`) en cada mensaje.
- Protección contra fórmulas maliciosas al abrir la lista en Excel.
- Borra los pedidos de más de 90 días (datos personales).
- En pantalla solo se muestran los últimos 4 dígitos del teléfono.

### Probarlo sin WhatsApp (5 minutos)
1. Instala [Ollama](https://ollama.com) y descarga el modelo: `ollama pull gemma3:4b`
2. Instala lo necesario: `pip install -r requirements.txt`
3. Conversa con el bot de ejemplo en la consola:
   ```
   python scripts/probar_bot.py
   ```
   Usa un negocio ficticio (`evals/bot_a_pedidos/negocio_ficticio.json`). Para tu negocio, copia ese archivo, cambia los datos y usa `--plantilla tu_negocio.json`.

### Conectarlo a WhatsApp
Usa la API oficial de Meta (WhatsApp Cloud API). Crea un archivo `.env` (nunca lo subas a git) con `META_VERIFY_TOKEN`, `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_APP_SECRET`, `TELEFONO_OFICIAL` y `BOT_PLANTILLA`, y arranca:
```
python -m src.whatsapp.puente_meta
```
El puente escucha en `http://localhost:8080/webhook`; para que Meta lo alcance necesitas un túnel HTTPS (por ejemplo, Cloudflare Tunnel).

### Medir la calidad del bot
`scripts/evaluar_bot.py` le hace preguntas de prueba (`evals/bot_a_pedidos/casos.json`) y revisa si responde bien: precios correctos, deriva cuando corresponde, no inventa descuentos.
```
python scripts/evaluar_bot.py --modelo gemma3:4b
```

### Pruebas
```
python -m pytest tests -q
```
Corren sin internet ni Ollama (todo simulado).

---

## English

A bot that lets **small businesses** (water delivery, corner stores, food distributors, small shops) take customer orders on WhatsApp automatically. It runs on **free, local AI** (Ollama) on a regular PC, with no paid cloud AI. Messages and prompts are in Spanish (built for Chile and Latin America).

### Features
- Answers customers with the business's prices, delivery areas and hours.
- Takes the order and logs it to a CSV list (opens in Excel).
- Notifies the owner on their phone via Telegram (optional).
- Hands off to a human on request: shares the owner's phone and stays silent with that customer until they type "menú".
- Out-of-hours handling and "the usual" (repeats the customer's last order).

### Built-in safety
- Deterministic (non-AI) filter that blocks invented prices or discounts.
- Verifies Meta's `X-Hub-Signature-256` on every webhook call.
- CSV formula-injection protection, 90-day data retention, masked phone numbers in logs.

### Quick start (no WhatsApp needed)
```
ollama pull gemma3:4b
pip install -r requirements.txt
python scripts/probar_bot.py
```

### Connect to WhatsApp
Uses Meta's official WhatsApp Cloud API. Put your keys in a `.env` file (never commit it) and run `python -m src.whatsapp.puente_meta`. Expose `localhost:8080/webhook` with an HTTPS tunnel.

### Evaluate the bot
`scripts/evaluar_bot.py` runs test conversations from `evals/bot_a_pedidos/casos.json` against a local model and scores the answers.

### Tests
`python -m pytest tests -q` — runs fully offline (network and model are mocked).

### Status
Early stage. Preparing the first pilot with a real local business. Feedback and contributions are welcome.

## License
MIT. See `LICENSE`.
