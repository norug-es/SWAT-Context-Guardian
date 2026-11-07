# Instalación en Codex CLI (Windows, Linux y Termux)

## Requisitos

- Codex CLI instalado y accesible con `codex --version`.
- Python 3.11 o superior (`python --version` o `py -3.11 --version`).
- Acceso al directorio local de usuario. Los logs JSONL deben existir para obtener telemetría; si la versión o modo de ejecución no los produce, el monitor informa ausencia de medición.
- El supervisor es un proceso distinto de la skill: **instalar la skill no inicia el monitor**.

## Windows PowerShell

Descomprime `SWAT-Context-Guardian-v0.2.0.zip` en `Downloads`. Su carpeta debe contener `SKILL.md` y `scripts/`.

```powershell
cd "$HOME\Downloads\swat-context-guardian"
python .\scripts\install_global.py                 # vista previa
python .\scripts\install_global.py --apply          # instalación explícita, sin sobrescribir

$g = "$HOME\.agents\skills\swat-context-guardian\scripts\guardian.py"
python $g doctor
python $g status
python $g watch --interval 10
```

Si tu comando es `py` en lugar de `python`, usa `py -3.11` (o una versión superior). `watch` queda en primer plano: `Ctrl+C` para detenerlo.

## Linux / Termux / macOS

```bash
cd ~/Downloads/swat-context-guardian
python3 scripts/install_global.py
python3 scripts/install_global.py --apply
python3 ~/.agents/skills/swat-context-guardian/scripts/guardian.py doctor
python3 ~/.agents/skills/swat-context-guardian/scripts/guardian.py status
python3 ~/.agents/skills/swat-context-guardian/scripts/guardian.py watch --interval 10
```

Termux suele recibir descargas en `~/storage/downloads`; ajusta el `cd` según tu dispositivo. El monitor solo identifica sesiones que ese sistema pueda leer (no sesiones de otro equipo).

## Uso en Codex CLI

Abre una sesión nueva de Codex o ejecuta `/skills` para localizar la skill. Invócala explícitamente:

```text
$swat-context-guardian diagnostica el contexto y prepara un checkpoint de este repo.
```

## Si la skill ya existe

El instalador bloquea por defecto cualquier sobrescritura. Revisa primero la copia anterior. Solo tras aprobación explícita: `python scripts/install_global.py --apply --replace`. Se crea una carpeta `.backup-...` junto a la skill; comprueba que existe antes de eliminar nada.

## Compactación nativa (independiente del watcher)

```powershell
python "$HOME\.agents\skills\swat-context-guardian\scripts\native_compaction.py" --percent 80
# Solo si has verificado compatibilidad y autorizado modificar config.toml:
python "$HOME\.agents\skills\swat-context-guardian\scripts\native_compaction.py" --percent 80 --apply --acknowledge-compatibility
```

Este ajuste es dependiente de versión, no está habilitado por el instalador y no demuestra que haya ocurrido una compactación. Conservar el backup y respetar cualquier configuración existente.

## Verificaciones

```powershell
python -m unittest discover -s tests -v
```

Referencia oficial: https://learn.chatgpt.com/docs/build-skills
