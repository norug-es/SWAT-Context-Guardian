# Changelog

## v0.4.0-intelligence (rama experimental)

- Dashboard adicional en /intelligence con heatmaps de calendario y horas, tendencias, composición, rachas, modelos y proyectos.
- Gráfico del riesgo de contexto de sesiones actuales, sin confundir recientes con procesos activos.
- API de analítica local con límites de escaneo, deduplicación, cobertura parcial explícita y cache.
- Adaptador ccusage opcional para costes y agentes; se mantiene separado de los contadores Codex JSONL.
- Adaptador opcional Win-CodexBar CLI para cuotas multiproveedor, sin importar credenciales.
- Nuevas regresiones y GitHub Actions de Python y JavaScript. No se han modificado el supervisor, la skill ni los checkpoints originales.
- Sin instalador nativo ni verificación en Windows real a la fecha; no release estable.

## v0.3.1 — Identidad y actividad de sesiones

- Consolidación de JSONL repetidos por `session_id`; conserva archivos fuente e historial de mediciones por ruta.
- Última medición temporal válida, separada del último cambio del archivo.
- Estados diferenciados: activa verificada, reciente no verificada e histórica.
- Filtros de estado, historial en ficha, copiar ruta y abrir carpeta Windows mediante validación local.
- Corrección de datos WS obsoletos en reconexión y sin confundir listados de hilos con actividad.
- 15 pruebas locales pasadas; sin comprobación todavía en Windows ni en el Codex real del usuario.
- Sin borrado de historiales, backups automáticos ni compactación automática.

## v0.3.0 — Control Center

- Panel local de sesiones agrupadas por proyecto, métricas, alertas y checkpoints de metadatos.
- Escáner incremental de rollouts JSONL en modo solo lectura.
- Integración opcional con Codex App Server mediante WebSocket loopback y token local.
- Notificaciones Windows con `winotify` y notificaciones de navegador opcionales.
- SQLite local para alertas, sin almacenar transcripciones ni claves.
- Protecciones para acciones POST (Host, Origin, token local).
- Documentación de instalación y guía de App Server. READMEs español, inglés y portugués.
- 12 pruebas en entorno aislado; no se ha probado con el binario de Codex del usuario ni con toasts reales de Windows.

## v0.2.0 — Skill & documentación

- Instalador global conservador, skill, monitor CLI y documentación multilingüe.
- Banner de SWAT Context Guardian.
