# Instalación en Codex Desktop / aplicación de escritorio

Codex Desktop y Codex CLI pueden descubrir skills desde el directorio global del usuario `~/.agents/skills/` cuando funcionan en **el mismo entorno local y bajo el mismo usuario**. Un backend remoto, Windows vs. WSL, o una sesión en otro equipo puede tener otro HOME y otros logs.

## Pasos

1. Instala primero la skill con el instalador del paquete en el mismo sistema donde se ejecuta Codex Desktop. Revisa [INSTALAR_CODEX_CLI.md](INSTALAR_CODEX_CLI.md).
2. Comprueba que existe `~/.agents/skills/swat-context-guardian/SKILL.md` y `agents/openai.yaml`.
3. Abre o reinicia Codex Desktop. Ve a **Skills** en la interfaz, cuando esté disponible, y busca **SWAT Context Guardian**; también puedes seleccionarla en el editor con `$swat-context-guardian`.
4. Prueba: `Revisa el contexto del proyecto actual sin modificar archivos ni procesos`.
5. En una terminal aparte, ejecuta el supervisor Python `status` o `watch`. Desktop no lanza automáticamente el watcher por detectar la skill.

## Qué funciona y qué no

- ✅ Aplicar el procedimiento descrito en `SKILL.md`, con las herramientas y permisos disponibles.
- ✅ Monitorizar **logs locales** que el supervisor pueda leer; estado y métricas aproximadas.
- ✅ Checkpoint explícito / handoff Markdown generado desde material verificado.
- ❌ No garantiza acceso a sesiones remotas, otras cuentas ni chats de ChatGPT.
- ❌ No compacta hilos externos de forma autónoma. La compactación activa requiere funciones disponibles y permiso explícito.
- ❌ No altera la configuración de Codex Desktop durante la instalación.

Si no aparece la skill, confirma la identidad del usuario, el HOME/CODEX_HOME efectivo, el directorio y reinicia la aplicación. No copies configuraciones de un perfil a otro sin revisarlas.

Referencias: https://learn.chatgpt.com/docs/build-skills y https://learn.chatgpt.com/docs/developer-commands
