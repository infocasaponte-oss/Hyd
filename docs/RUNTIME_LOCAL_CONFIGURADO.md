# Runtime local HYDRA configurado

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

La configuración operativa local está en `config/models.hydra-local.yaml` y usa
`hydra-q5-candidate:latest`, cuyo GGUF es Q5_K_M. El calibrador externo se crea
desde las 120 filas compatibles de la partición de calibración v3 y queda en
`models/kev-calibrator-v3.json`, con el hash del archivo de calibración.

La validación real mediante `HydraEngine.query()` terminó con estado `completed`,
modelo `hydra-q5-candidate`, modo local y sin caché. La primera llamada tardó
18.100,82 ms por carga fría y preparación del kernel; esta medida no representa
latencia caliente. `verified=false` se conserva correctamente porque el motor no
debe convertir una comprobación externa posterior en verificación interna.

Kev se consulta como observador en modo `BALANCED`, con timeout de 2 segundos,
opciones canónicas y calibrador cargado. Sus observaciones no sustituyen el router
ni autorizan herramientas. La compuerta `review/security/privacy/abstain` se aplica
antes de Kev.

El artefacto generativo Q5 es `models/hydra-q5/HYDRA.gguf`:

- Q5_K_M, 1.125.049.920 bytes.
- SHA256 `634eb99a1bde8bde375206dabd0bfd45ce5be2106abe55a16dd8a49b97f8a650`.
- Manifiesto `models/hydra-q5/build-manifest.json`.

Reproducción:

```powershell
.venv/Scripts/python.exe -m hydra.training.create_calibrator
.venv/Scripts/python.exe -m hydra.training.validate_unified_runtime
```

Evidencia: `data/evaluations/unified-runtime-live.json`. Esta ejecución confirma
la tubería local y la identidad configurada; no certifica calidad general ni
aprueba aún el modelo para producción.
