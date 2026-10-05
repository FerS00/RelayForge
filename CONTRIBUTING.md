# Contribuir

RelayForge está en desarrollo temprano. El [plan revisado](docs/PLAN_PROYECTO.md) es borrador pendiente de aprobación; no ejecutar fases nuevas desde una petición de documentación. Consulta los [bloqueos actuales](docs/testing.md) y preserva WIP anterior al preparar cambios para Git.

## Requisitos de desarrollo

- Windows con Python 3.13+, Git, `uv`, Node.js y npm.
- Un checkout local. Las pruebas deben usar agentes falsos sin credenciales. El test de comparación fingerprint sustituye `_agent` con un doble sintético; las pruebas no invocan CLIs reales de agentes.

## Preparación y verificaciones

```powershell
uv sync --all-groups
npm --prefix web ci
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/relayforge
uv run pytest -q
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test
npm --prefix web run build
uv run python scripts/check_personal_paths.py
semgrep scan --config p/default --metrics off --error --no-git-ignore src/relayforge web/src
```

No uses credenciales reales en fixtures. No agregues capturas de sesiones de agente: crea JSONL sintético mínimo para las pruebas del parser. Mantén secretos fuera de eventos, resúmenes, logs y artefactos; la redacción de RelayForge es defensa en profundidad.

Los cambios que afectan autorización, acceso a archivos, procesos, reintentos, aprobación o entrega necesitan pruebas de regresión. No pruebes con una cuenta real ni publiques desde CI. La CI usa repositorios temporales y agentes falsos.

Semgrep cubre `src/relayforge` y `web/src`, que se distribuyen como producto. `pocs/` contiene utilidades locales fuera del paquete; sus llamadas de diagnóstico a localhost o a una URL Tailscale se revisan por separado.

Consulta [SECURITY.md](SECURITY.md) para el modelo de amenazas y el canal de reporte.
