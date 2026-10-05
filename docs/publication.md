# Preparación del repositorio para Git

Estado: documentación y código local pasan auditoría de gates automatizados; producto en **desarrollo temprano**. La aceptación Docker, proveedores reales, móvil físico, recovery y CI remota sigue pendiente.

## About propuesto

```text
Self-hosted Windows work console for Claude Code, Codex, and Antigravity, with Git worktrees, auditable jobs, human approvals, and private mobile access. Early development.
```

No se ha editado el About remoto. Website puede dejarse vacío hasta disponer de una URL pública de documentación; no publicar el hostname privado Tailscale.

## Topics propuestos

```text
self-hosted ai-agents agent-orchestration claude-code codex-cli antigravity git-worktree human-in-the-loop fastapi python react typescript sqlite windows docker tailscale early-development
```

Los topics son metadatos propuestos, no una declaración de compatibilidad con Linux, disponibilidad continua o soporte de producción.

## Documentación candidata

README en inglés y estructura de [Overseer](https://github.com/FerS00/Overseer): presentación/badges, Overview, flujo, decisiones/arquitectura, Tech Stack, Requirements, Quickstart, desarrollo, documentación, Troubleshooting y License. Plan y guías técnicas en español. Screenshots y badges de CI passing se omiten hasta obtener material sintético/publicable y evidencia real.

Plan canónico revisado, checkpoint, índice, uso, arquitectura, instalación, Docker, testing, SECURITY y CONTRIBUTING forman el conjunto vigente. Las especificaciones y POCs son historia etiquetada; el archivo del plan anterior conserva decisiones sin competir con la fuente canónica.

## Inspección antes de una entrega futura

1. Verificar raíz Git, rama/HEAD, remoto y referencia de destino antes de cada entrega.
2. Revisar el WIP de Fases 2–10 y consola junto con esta documentación; conservar cambios previos y publicar solo el conjunto revisado.
3. Confirmar que el conjunto candidato excluye `.env*`, tokens, perfiles CLI, DBs, logs, fingerprints, NDJSON de runtime, `pocs/results/`, cachés, Playwright y Graphify. No confiar solo en `.gitignore` si hay archivos ya tracked.
4. Ejecutar checks de enlaces/documentos, rutas personales y escáner de secretos sobre los archivos candidatos. Un escaneo de rutas no equivale a un escaneo de secretos.
5. Los gates locales aprobados no acreditan aceptación operativa ni CI remota. Ejecutar comprobaciones con Docker, proveedores y teléfono según el plan.
6. Obtener autorización explícita para la operación Git exacta; una preparación local no la concede por sí sola.

Un mensaje adecuado para el conjunto de consola/documentación es `feat: add agent development work console`. No añadir trailers de autoría AI.

## Límites actuales

Ruff I001 y el uso de CLI real en el test de fingerprint están corregidos y auditados. Autenticación/Job Docker, teléfono físico, recovery y CI final siguen abiertos. La documentación puede explicar esas limitaciones en un repositorio público; no presentarlas como capacidades aceptadas ni publicar artefactos privados para demostrar pruebas.

## Comprobaciones de esta preparación

Enlaces locales del conjunto Markdown comprobados sin roturas; escáner de rutas personales sobre snapshot candidato sin hallazgos; `.env.docker`, Playwright, caché de pairing y Graphify excluidos por Git. El escaneo de secretos Gitleaks no se ejecutó porque su CLI no está disponible; queda registrado como limitación de esta entrega.
