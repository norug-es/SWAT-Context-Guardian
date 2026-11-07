# Arquitectura y modelo de seguridad

## Capas

1. **Skill global** (`SKILL.md`) — instrucciones y reglas de evidencia. Se activa dentro de un agente cuando se invoca o coincide con la solicitud; no se ejecuta entre turnos.
2. **Monitor Python** (`scripts/guardian.py`) — inspecciona en modo lectura los JSONL locales de Codex. Puede calcular una ocupación **aproximada**, notificar umbrales y escribir alertas propias. No extrae transcripciones para el checkpoint.
3. **Checkpoint/handoff** — el usuario o agente autorizado aporta hechos; el programa crea un JSON y Markdown revisables, almacenados en `CODEX_HOME/context-guardian/checkpoints/`.
4. **Compactación nativa** — `scripts/native_compaction.py` solo propone o modifica expresamente un ajuste de Codex si el usuario verifica compatibilidad y lo autoriza. No fuerza un `thread/compact/start` ni accede a servidores externos.
5. **ChatGPT** — skill de instrucciones separada o instrucciones de Proyecto; no acceso a archivos locales ni a la métrica de uso de contexto de ChatGPT.

## Política

| Umbral aproximado | Acción del monitor | Qué no hace |
| --- | --- | --- |
| 60 % | Mostrar alerta | No reescribe prompt |
| 70 % | Recomendar checkpoint | No extrae automáticamente decisiones del chat |
| 80 % | Sugerir revisión de compactación nativa | No compacta automáticamente |
| 90 % | Recomendar handoff | No termina ni inicia sesiones |

## Límites

- Las estructuras JSONL de Codex pueden evolucionar. Sin `last_token_usage.total_tokens` y `model_context_window`, mostrar `SIN MEDICIÓN`.
- El valor calculado no es el consumo exacto empleado por Codex para la compactación; existen tokens de sistema, prefijos, presupuestos y ajustes por modelo.
- Si Docker, WSL, Termux o una sesión remota usan distinto directorio de usuario, no compartirán automáticamente los rollouts.
- No hay integración MCP activa, API web, sincronización a ChatGPT, ni daemon instalado como servicio.
- El monitor no debe exponerse públicamente ni compartirse el directorio `.codex`, porque otros archivos de esa carpeta pueden incluir información sensible.

## Seguridad de la cadena de suministro

Leer los scripts antes de ejecutar. Ejecutar `python -m unittest discover -s tests -v`. El instalador tiene dry-run por defecto y no edita `~/.codex/config.toml`. El ajuste opcional de compactación conserva copia de seguridad y rechaza claves ya existentes. No usar escalado de privilegios ni ejecutar `watch` como administrador sin necesidad.
