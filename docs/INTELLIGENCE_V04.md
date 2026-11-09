# SWAT Context Guardian v0.4 — Intelligence (rama experimental)

Esta ampliación preserva el monitor, la skill global, los checkpoints y el handoff v0.3.1. La rama de desarrollo es **feature/context-guardian-v0.4-intelligence**. Todavía no es una versión estable ni ha sido validada en el Windows del usuario.

## Visualizaciones disponibles

| Vista | Fuente y significado |
| --- | --- |
| Calendario de calor | Deltas de contadores Codex JSONL, 7/30/90/365 días |
| Calor horario 7 × 24 | Eventos por día/hora, en UTC |
| Evolución diaria y semanal | Tokens observados, no facturación |
| Composición input/output/cache | La caché está incluida en input, no se suma por separado |
| Modelos y proyectos | Consumo identificado por modelo y proyecto |
| Pico diario y rachas | Agregados de la ventana seleccionada |
| Riesgo de contexto | Sesiones recientes o verificadas con porcentajes aproximados |
| Cuotas Codex | App Server propio de Codex, consulta manual |
| Proveedores Windows | Win-CodexBar CLI, consulta manual |
| Costes y agentes | ccusage CLI, reporte independiente y manual |

**Fuentes separadas:** los datos de ccusage pueden incluir Codex. No se deben sumar con JSONL, ni confundir cuotas con tokens o consumo de contexto. Los costes de ccusage son estimaciones y pueden ser incompletos cuando hay modelos sin precio.

## Instalación Windows / PowerShell 7

Descarga la rama de desarrollo en otra carpeta. Detén con Ctrl+C el Control Center anterior si ocupa el puerto 8765. Ejecuta en la raíz:

    .\start-control-center.ps1 -WithToasts -Port 8765

Abre http://127.0.0.1:8765/intelligence desde el navegador o la barra lateral del panel existente.

Para visualizar datos sintéticos claramente identificados:

    .\start-control-center.ps1 -Demo -Port 8766

La demo no consulta fuentes de pago ni genera nuevos archivos de sesiones.

### Windows portátil sin instalación de Python (beta)

Se ha generado un ejecutable portátil de Windows x64 mediante GitHub Actions y
**se comprobó que arranca y sirve el dashboard en modo demo en un runner Windows**.
Este paquete sigue siendo experimental y no está firmado digitalmente.

- Compilación y prueba: https://github.com/norug-es/SWAT-Context-Guardian/actions/runs/42599153564
- En la sección **Artifacts** descarga **SWAT-Context-Guardian-v0.4-Windows-x64-beta**.
- **Descomprime el ZIP completo**; NO extraigas solo el .exe, ya que necesita sus librerías y assets.
- Ejecuta **SWAT-Guardian.exe** como usuario normal. Se inicia en 127.0.0.1:8765 y abre el navegador.
- El proceso termina cuando cierras su consola. No instala servicios ni tareas de inicio.
- Para probar sin acceder a sesiones, abre PowerShell en la carpeta extraída:

    .\SWAT-Guardian.exe --demo --port 8766

No combines esta beta con otra instancia en el mismo puerto. Si Windows advierte que
el binario está sin firmar, comprueba su procedencia y el resultado de CI antes de
confiar en él. La **compilación en CI no valida** acceso a tus cuentas reales de Codex,
ccusage o Win-CodexBar, ni sus permisos y versiones en tu máquina.

### ccusage (opcional)

Instala ccusage desde sus canales oficiales y deja el comando en PATH. Ejemplo si tienes Node.js:

    npm install -g ccusage
    ccusage daily --by-agent --json

El botón **Leer ccusage local** invoca únicamente ese CLI, sin npx y sin descargas automáticas. Devuelve agregados por día y por agente; no retorna transcripciones, cuentas ni rutas brutas. Puede incluir Codex y no se mezcla con la serie Codex JSONL.

### Win-CodexBar CLI (opcional)

La documentación del CLI es https://github.com/nesszer/Win-CodexBar/blob/main/docs/CLI.md

El ejecutable que debe figurar en PATH es **codexbar-cli.exe** de su release, no codexbar.exe (que puede abrir la aplicación gráfica):

    codexbar-cli.exe usage --json

El botón **Consultar proveedores** ejecuta ese CLI. Consulta solo proveedores habilitados en Win-CodexBar y puede efectuar solicitudes a sus servidores externos. Guardian solo expone nombre del proveedor, cuotas porcentuales, ventanas y estado saneados, nunca correo, token, cookie ni identidad de cuenta.

## API local

- GET /intelligence — panel HTML sin CDN.
- GET /api/intelligence?days=90 — datos agregados Codex.
- POST /api/intelligence/ccusage — requiere token local y ejecuta ccusage solo por acción explícita.
- POST /api/intelligence/windows-providers — requiere token local y ejecuta Win-CodexBar CLI solo por acción explícita.
- GET /api/status y GET /api/codex/account — endpoints existentes, sin modificar su semántica.

El servidor sigue enlazado a 127.0.0.1 mediante el lanzador existente. Los nuevos endpoints no modifican sesiones, configuraciones o procesos externos.

## Privacidad, exactitud y rendimiento

Se leen archivos rollout-*.jsonl bajo CODEX_HOME/sessions sin seguir enlaces simbólicos. Se interpretan solo eventos session_meta, turn_context y token_count; no se conserva texto de mensajes. No se añaden bases de datos de mensajes ni lectores de credenciales.

El analizador usa hasta 600 archivos, hasta los últimos 16 MiB por archivo, aprox. 128 MiB acumulados y hasta 120.000 eventos. Cachea resultados durante 60 segundos. coverage.partial informa de pérdidas por límites, errores o truncamientos.

La deduplicación usa el ID lógico de sesión, timestamp y valores de contadores. Si retroceden los contadores, se omite esa lectura como nuevo consumo. Los datos pueden ser parciales cuando hay logs antiguos, muy grandes o incompletos. No se dispone de una reconciliación contable global.

La hora de los mapas es UTC. Los nombres de proyectos son el basename de su ruta, por lo que dos directorios homónimos pueden tener la misma etiqueta.

## Pruebas

    python -m pip install -r control_center/requirements.txt httpx
    python -m unittest discover -s tests -v

GitHub Actions verifica las regresiones existentes, los agregados de tokens, sanitización de datos, interfaces REST y sintaxis JavaScript.

## Límites pendientes

No se ha demostrado el seguimiento de todos los subagentes ajenos al App Server, ni un handoff totalmente automático, ni un instalador Windows firmado, ni monitorización de equipos remotos, ni facturación exacta. La demo no sustituye las pruebas reales de Windows y de cuotas de proveedores.

## Licencias

SWAT Context Guardian: MIT. Win-CodexBar y ccusage: MIT. Se invocan sus CLI opcionales como procesos separados, sin copiar bibliotecas. De CodexBar Swift, GPL-3.0, se han estudiado ideas funcionales pero no incorporado código fuente.
