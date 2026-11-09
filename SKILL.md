---
name: swat-context-guardian
description: Monitorizar y gestionar el contexto de sesiones Codex CLI y sus agentes; preparar checkpoints verificables, compactación nativa autorizada y relevos seguros entre sesiones y proyectos. Usar cuando el usuario menciona tokens, saturación del contexto, 60/70/80/90 %, compaction, handoff o continuidad de trabajo en Codex.
---

# SWAT Context Guardian

Skill global y multi-repositorio, ampliada con Control Center v0.3.1. Su objetivo es preservar **decisiones verificadas, restricciones y continuidad** sin alterar los procesos activos.

## Reglas de seguridad

1. Identificar proyecto, sesión, ruta `CODEX_HOME`, estado de Git y versión de Codex antes de proponer acciones.
2. Separar siempre: **observado**, **declarado por el usuario** y **no verificado**.
3. El monitor clásico lee archivos `rollout-*.jsonl` de Codex; el Control Center puede conectarse opcionalmente a App Server por WebSocket de localhost para recibir **metadatos**, sin modificar conversaciones. No presentar el porcentaje calculado como el medidor interno exacto de Codex.
4. Nunca prometer que esta skill se ejecuta sola entre turnos. El demonio `watch` requiere un proceso o servicio externo activo.
5. No editar `~/.codex/config.toml`, `~/.codex/AGENTS.md` ni archivos de otros repositorios sin autorización explícita. Conservar configuraciones existentes, realizar copia de seguridad y validar la versión.
6. No ejecutar `/compact`, `thread/compact/start`, cerrar/crear/reanudar sesiones, alterar producción, Docker, migraciones o Git por una alerta solamente. Las operaciones activas exigen autorización específica y capacidades realmente disponibles.
7. Los checkpoints no deben contener secretos, tokens de acceso, contraseñas, volcado completo de chat ni datos sensibles innecesarios.
8. No fusionar evidencias de proyectos distintos; resolver el proyecto actual con CWD y rama/HEAD, nunca con una etiqueta genérica como "SWAT".
9. Cuando la métrica no esté disponible, decir `SIN MEDICIÓN`, sin inventar porcentajes.

## Flujo operativo

### A. Diagnóstico (read-only)

Desde la carpeta de la skill:

```sh
python scripts/guardian.py doctor
python scripts/guardian.py status
python scripts/guardian.py status --json
```

El programa toma `CODEX_HOME` del entorno o usa `~/.codex` y busca sesiones recientes. Para sesiones antiguas se puede ampliar `--hours 168` antes del subcomando.

### B. Vigilancia de umbrales

```sh
python scripts/guardian.py watch --interval 10
```

Interpretación de alertas estimadas:

- 60 %: informar y valorar reducción de salidas voluminosas.
- 70 %: recopilar decisiones/evidencias y preparar checkpoint.
- 80 %: verificar si Codex tiene compactación nativa habilitada; si no, proponerla **sin modificar config por defecto**.
- 90 %: proponer relevo con checkpoint; no iniciar nueva sesión automáticamente.

Los eventos se registran en `~/.codex/context-guardian/alerts.jsonl`. El monitor no crea resúmenes ni compacta por sí mismo. El cálculo usa solo `last_token_usage.total_tokens / model_context_window` si aparecen ambos en eventos de Codex. El valor puede diferir del contexto real utilizable.

### C. Checkpoint verificable

Antes de prepararlo, revisar `git status` y los artefactos relevantes de manera autorizada. **No inferir decisiones de nombres de archivo**. Solicitar las decisiones pendientes si faltan. Usar `--summary`, `--decisions`, `--evidence`, `--pending`, `--next-step`, `--safety` solo con información respaldada; si algo falta, dejarlo sin registrar.

```sh
python scripts/guardian.py checkpoint --project /ruta/a/proyecto \
  --summary "Hechos contrastados" \
  --decisions "Decisiones aprobadas" \
  --evidence "Pruebas, rutas y hashes comprobados" \
  --pending "Pendientes reales" \
  --next-step "Siguiente paso seguro" \
  --safety "Restricciones y autorizaciones"
```

`checkpoint` captura metadatos Git y **únicamente el texto explícito proporcionado**. No resume automáticamente los rollouts. La salida es un JSON local, con etiqueta clara de procedencia.

### D. Relevo

```sh
python scripts/guardian.py handoff --checkpoint /ruta/al/checkpoint.json
```

Mostrar el Markdown generado y pedir su revisión para secretos y errores. Al continuar en otro hilo, verificar nuevamente repo, rama, commit, árbol y pruebas; no asumir que el contexto oculto se transfirió.

### E. Compactación nativa (opt-in)

Consultar `references/COMPACTACION.md` y usar primero:

```sh
python scripts/native_compaction.py --percent 80
```

Solo cuando el usuario confirme la compatibilidad **de su versión instalada** y autorice modificar el archivo de configuración:

```sh
python scripts/native_compaction.py --percent 80 --apply --acknowledge-compatibility
```

El instalador añade exclusivamente la clave de compactación global si no existe y guarda copia de seguridad del config; no garantiza que la compactación ocurra. Si la clave ya existe, se niega a sobrescribirla. Nunca asumir que un `thread/compact/start` puede invocarse en una sesión externa sin conexión a la instancia propietaria.

## Salida esperada al usar esta skill

Dar un reporte breve con **sesión/proyecto**, **medición y fiabilidad**, **estado del checkpoint**, **si hubo cambios** y **siguiente acción recomendada**. Mantener decisiones y evidencias diferenciadas. No afirmar `compactado`, `respaldado` o `relevado` sin evidencia.

### F. Centro de control visual v0.3.1 (opt-in)

El panel está separado del daemon tradicional y **no se inicia al invocar la skill**. Para abrirlo:

```powershell
.\start-control-center.ps1
```

Para habilitar los avisos Windows:

```powershell
.\start-control-center.ps1 -WithToasts
```

Para conectar App Server utiliza dos terminales y token local, según `docs/CONTROL_CENTER.md`. El panel no ejecuta comandos de Codex, no puede gestionar hilos ajenos por mera conexión y no realiza compactación automática. Las notificaciones solo están disponibles mientras el proceso está en ejecución; los checkpoints creados desde la UI son **solo metadatos**.

## Recursos

- `scripts/guardian.py`: diagnóstico, vigilancia, checkpoints, handoff.
- `scripts/native_compaction.py`: previsualización / habilitación explícita de compactación nativa.
- `scripts/install_global.py`: instalador conservador de skill global.
- `references/COMPACTACION.md`: límites, compatibilidad y modelo de seguridad.
- `references/CONTINUIDAD.md`: formato recomendado de handoff y guía para distintos proyectos.

- `control_center/`: backend FastAPI, monitor incremental, puente WS y panel web.
- `docs/CONTROL_CENTER.md`: instalación, WS autenticado, toasts, limitaciones y API local.

### G. Interpretación fiable de sesiones

- El panel v0.3.1 **consolida por `session_id`** los archivos JSONL repetidos y expone sus referencias en el historial de la ficha. No presentar el número de archivos como número de procesos.
- `Activa verificada` requiere estado `active` reciente y enlace vigente con App Server. Los cambios de archivos JSONL solos son **recientes, no ejecución verificada**.
- El porcentaje representa la última medición válida por tiempo, no la medición más alta. Revisar marcas temporales antes de decidir una alerta o checkpoint.
- Un botón `Abrir carpeta` de Windows solo abre una ubicación ya observada bajo `CODEX_HOME/sessions` por acción explícita. Nunca borrar archivos de rollout sin auditoría.
