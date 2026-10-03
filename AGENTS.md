# Instrucciones del repositorio

- Plan canónico: `docs/PLAN_PROYECTO.md`; checkpoint: `docs/ESTADO_TRABAJO.md` cuando exista.
- Implementa solo la especificación aprobada y las rutas que enumera.
- No hagas commit ni push. No incluyas rutas personales, credenciales ni datos de `.env`.
- No uses `shell=True` ni flags `dangerously*`.
- Escribe UTF-8 sin BOM y usa LF salvo en archivos `.ps1`.
- `pocs/` es desechable y no puede importarse desde `src/`.
- Las pruebas no invocan CLIs reales de agentes; usan dry-run o dobles.
