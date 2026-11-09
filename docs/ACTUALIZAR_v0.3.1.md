# SWAT Context Guardian · actualización segura v0.3.1

## Problema corregido

En v0.3.0, un mismo ID de sesión de Codex podía aparecer en varias filas al estar registrado en varios archivos `rollout-*.jsonl`. Esos archivos son **fuentes históricas** y no prueban la existencia de múltiples procesos activos.

v0.3.1 deduplica por `session_id`, mantiene las rutas en **Ver historial** y utiliza la medición de tokens con fecha más reciente (no el porcentaje más alto). También distingue:

- **Activa verificada:** App Server conectado con estado `active` fresco (≤60 segundos).
- **Reciente:** modificación de JSONL o evento observado en las últimas 24 horas, sin prueba de ejecución.
- **Histórica:** registros antiguos o sin prueba temporal reciente.

## Actualizar Windows sin modificar Codex

1. Detén **solo el Control Center v0.3.0** desde su terminal PowerShell, pulsando `Ctrl+C`. No cierres procesos Codex ni borres JSONL.
2. Descarga `SWAT-Context-Guardian-v0.3.1-Control-Center.zip` y colócalo en `Downloads`.
3. Ejecuta:

```powershell
$Zip = "$HOME\Downloads\SWAT-Context-Guardian-v0.3.1-Control-Center.zip"
$Dest = "$HOME\Downloads\Guardian-v031"
Expand-Archive -LiteralPath $Zip -DestinationPath $Dest -Force
cd "$Dest\swat-context-guardian"
.\start-control-center.ps1 -WithToasts
```

4. Abre `http://127.0.0.1:8765`.
5. Comprueba que el contador dice **Sesiones únicas**, visita **Sesiones → Históricas** y pulsa **Ver → Ver historial** en un hilo que tenga varios archivos.

Si ya tenías App Server autenticado funcionando en otra terminal, inicia el nuevo panel con las mismas opciones y token que antes:

```powershell
.\start-control-center.ps1 -WithAppServer -WithToasts -TokenFile "$HOME\.codex\context-guardian\ws-token.txt"
```

**No es necesario reinstalar la skill global** para utilizar el panel nuevo. Si quieres actualizar la skill instalada, revisa primero el diff y utiliza el instalador conservador, que hace backup antes de reemplazar. No modifiques `config.toml` ni rutas de producción.

## Qué NO hace esta actualización

- No borra historiales, agentes ni archivos JSONL.
- No crea backups horarios ni diarios.
- No inicia, detiene, compacta ni cambia sesiones de Codex.
- No puede acreditar actividad de un proceso basándose solo en la modificación de un archivo.
- No garantiza recibir notificaciones de todas las sesiones abiertas por otros clientes desde una conexión nueva de App Server.

## Ventana temporal del historial

El panel lee los archivos encontrados en el período configurado (`--hours 72` por defecto) hasta el límite de descubrimiento (`--limit 60`). El filtro **Históricas** no busca automáticamente todo el historial del disco. Si necesitas más archivos, inicia el backend directamente con otros parámetros tras valorar rendimiento y privacidad.

## Pruebas

Se han superado 15 pruebas locales (incluyendo duplicados y WebSocket simulado), y una prueba visual de interfaz con datos sintéticos. **No está verificado todavía en tu Windows/Codex real.**
