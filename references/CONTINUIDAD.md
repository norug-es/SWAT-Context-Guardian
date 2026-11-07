# Continuidad segura y transferencia de contexto

## Datos mínimos del checkpoint

- **Identidad del proyecto**: ruta real, repo, HEAD, rama.
- **Objetivo**: resultado buscado y alcance autorizado.
- **Hechos verificados**: pruebas, rutas, hashes, outputs reproducibles; estado PASS / FAIL / NOT_PROVEN si aplica.
- **Decisiones aprobadas**: distinguir explícitamente diseño aprobado de autorización de implementación.
- **Restricciones**: seguridad, producción, ramas, versiones, migraciones, datos personales.
- **Pendientes**: tareas con estado y causa del bloqueo.
- **Siguiente operación segura**: una acción, preflight y criterios de éxito.

## Handoff entre sesiones

1. El monitor informa un nivel de riesgo (estimado).
2. Un humano o un agente con acceso autorizado documenta un checkpoint real.
3. El script convierte ese checkpoint en un `.md` autocontenido.
4. Una nueva sesión recibe ese Markdown y vuelve a verificar la evidencia antes de ejecutar.
5. No se debe afirmar que existe relevo automático sin controlador de sesiones.

## Escala global/múltiples proyectos

Una única instalación global de la skill vive en `~/.agents/skills/swat-context-guardian/`. Los registros están en `CODEX_HOME/context-guardian/` y cada checkpoint incluye proyecto y sesión. No instalar AGENTS.md globalmente ni sobrescribir las instrucciones particulares de los proyectos. Adaptar objetivos y riesgos al repositorio actual.

Si se desea un servicio persistente, iniciar `watch` como proceso/servicio del sistema operativo después de confirmar sus permisos. La instalación de la skill no arranca un servicio.
