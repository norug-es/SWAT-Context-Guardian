# Compactación de contexto: compatibilidad y límites

## Confirmado en el código fuente actual de Codex (consultado el 7-11-2026)

- `model_post_turn_compact_threshold_percent` es una opción de configuración **de nivel superior** cuyo valor está entre 0 y 100 (0 desactiva la opción específica). Solicita compactación al final del turno en función del **contexto utilizable**, que no es necesariamente igual a la ventana total reportada.
- `model_auto_compact_token_limit` existe como mecanismo separado; su límite puede variar según el modelo y no conviene modificarlo sin necesidad.
- Codex puede emitir eventos `token_count` dentro de sesiones JSONL locales. El porcentaje estimado por nuestro monitor no coincide necesariamente con el cálculo interno por diferencias de prefill, scopes, modelos y tokens de respuesta.

Fuentes de referencia:
- https://github.com/openai/codex/blob/main/codex-rs/config/src/config_toml.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/config/mod.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/session/context_window.rs
- https://github.com/openai/codex/issues/10365
- https://developers.openai.com/api/reference/cli

**Advertencia:** La documentación del repositorio main puede ser más reciente que la versión instalada. No se ha probado esta opción en el equipo del usuario. No es correcto afirmar que se compactará exactamente al llegar al 80 % basado solo en este ajuste.

## Procedimiento de bajo riesgo

1. `codex --version`.
2. Revisar `~/.codex/config.toml` sin imprimir secretos en un chat.
3. `python scripts/native_compaction.py --percent 80` (solo vista previa).
4. Validar que su build de Codex admite ese campo.
5. Con autorización explícita: `python scripts/native_compaction.py --percent 80 --apply --acknowledge-compatibility`.
6. Reiniciar Codex y observar en los logs si se produce una compactación real al terminar un turno.

Para revertir, restaurar **solo** la copia de seguridad creada y tras revisar si ha habido cambios concurrentes. Nunca restaurar un config antiguo a ciegas.

## ¿Qué no hace el supervisor?

- No conoce el porcentaje exacto de contexto de ChatGPT web.
- No fuerza la compactación de sesiones Codex CLI ya abiertas.
- No invoca App Server ni APIs de pago.
- No guarda transcripciones, prompts, contraseñas ni razonamiento interno.
- No decide qué preservar semánticamente: eso lo produce un agente, con evidencia, durante la sesión.
