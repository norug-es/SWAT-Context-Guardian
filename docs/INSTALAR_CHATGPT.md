# ChatGPT: skill e instrucciones de proyecto

## Disponibilidad (verificada en noviembre de 2026)

La instalación directa de skills en ChatGPT se documenta para cuentas elegibles **Business, Enterprise, Healthcare y Edu**, según las opciones del workspace. No debe presumirse que la pestaña **Skills** aparezca en ChatGPT Plus. Tampoco debe presumirse sincronización de skills locales de Codex con ChatGPT.

Referencia: https://help.openai.com/es-es/articles/20001066-skills-in-chatgpt

## Opción A. Workspace con Skills habilitadas

1. En ChatGPT, abre **Plugins / Complementos** en la barra lateral.
2. Entra en la pestaña **Skills / Habilidades**.
3. Pulsa **Crear** → **Subir desde el ordenador**; selecciona `SWAT-Context-Guardian-ChatGPT-Skill.zip` (paquete de instrucciones, sin monitor local).
4. Espera el análisis y revisión de seguridad del workspace. Si se admite y habilita, invoca `@swat-context-guardian` o pide `revisar mi continuidad de proyecto con SWAT Context Guardian`.
5. Adjunta el checkpoint Markdown o JSON cuando quieras que ChatGPT prepare un handoff basado en evidencia.

**Limitación crucial:** esta skill opera sobre archivos o contexto realmente proporcionados; ChatGPT no obtiene por instalarla los registros `~/.codex/sessions/`, no sabe la ocupación real de su propio contexto y no puede activar la compactación nativa de Codex CLI. Para telemetría local haría falta una app/conector o MCP desplegado y autorizado por separado.

## Opción B. ChatGPT Plus o entorno sin Skills habilitadas

1. Crea un **Proyecto** en ChatGPT, por ejemplo `SWAT Context Guardian`.
2. Copia el contenido de [`CHATGPT_PROJECT_INSTRUCTIONS.md`](CHATGPT_PROJECT_INSTRUCTIONS.md) en las instrucciones del proyecto.
3. Añade únicamente checkpoints o resúmenes depurados y los documentos de continuidad que quieras consultar.
4. Usa el proyecto para revisar, redactar y mejorar los handoffs. No lo trates como un monitor activo ni como acceso remoto a Codex.

Las instrucciones de Proyecto son un sustituto **de procedimiento**, no una skill instalable ni un supervisor.

## ¿Cómo sincronizarlo realmente en el futuro?

Harían falta permisos expresos y un componente de integración que exponga solo métricas y checkpoints depurados. No publicar logs completos ni credenciales; preferir un servicio MCP de lectura, autenticado, con control por proyecto. **No está implementado en v0.2.0.**
