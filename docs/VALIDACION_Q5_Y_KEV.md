# Validación real y candidato Q5 — 30/09/2026

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Actualización posterior: la descarga original finalizó y se validó inferencia real
de Kev en CUDA, con tres clasificaciones correctas. Véase
[Kev GPU validado](KEV_GPU_VALIDADO.md). La sección de bloqueo inferior conserva
el estado del intento inicial.

## Resultado observado

Se ha construido `models/hydra-q5/HYDRA.gguf` desde el F16 fusionado del piloto.
Es una nueva cuantización Q5_K_M de los mismos pesos entrenados, no un nuevo
adiestramiento ni una mezcla de pesos de otras marcas. El Q4 original se conserva.

| Medida | HYDRA Q4_K_M | HYDRA Q5_K_M |
|---|---:|---:|
| Tamaño de archivo | 986.048.064 bytes | 1.125.049.920 bytes |
| Regresión nueva, 12 familias | 6/12 | 7/12 |
| Holdout piloto, 64 casos | 64/64 (evaluación anterior) | 64/64 (esta ejecución) |

En la comparación nueva mejora `prefix`, sin regresiones observadas. Q5 ocupa
aproximadamente un 14,1 % más. Doce tareas no bastan para demostrar mejora general;
persisten cinco fallos: deduplicación con listas anidadas, rachas consecutivas,
unión de intervalos, rotación y búsqueda de inserción. No se promociona a producción.
Los casos de regresión están expresamente excluidos del entrenamiento.

SHA256 Q5: `634eb99a1bde8bde375206dabd0bfd45ce5be2106abe55a16dd8a49b97f8a650`.
SHA256 F16 de origen: `a7b87e7f9996f2949e3d46c0453ab53813dc4b20018445526a5ef309f13052a8`.
Manifiesto local: `models/hydra-q5/build-manifest.json`; licencia de base conservada.
Ollama lo importa como `hydra-q5-candidate`; se verificó la identidad del GGUF
servido al inicio y al final de las evaluaciones.

## Motor

La petición real mediante `HydraEngine.query()` reveló un fallo de prefijo común
con las instrucciones anteriores. El prompt del razonador ahora exige respetar
el formato solicitado, firma, imports y casos límite, y no afirmar pruebas no
ejecutadas. La repetición pasó tres comprobaciones independientes en Docker.
No se han ajustado pesos utilizando este caso. Una repetición favorable no
establece una mejora estadística del prompt; ambos resultados quedan guardados.

La ejecución posterior utilizó solo `hydra-q5-candidate`, sin caché, en 2.527,98 ms.
Ollama reportó `size_vram=1.244.418.538`, igual al tamaño cargado reportado para ese
modelo; es una instantánea, no el pico de VRAM ni memoria exclusiva del proceso.
El motor devuelve `verified=false`: la verificación Docker posterior se registra
por separado y no se atribuye retroactivamente al motor.

El evaluador ahora exige una marca de finalización después de todas las aserciones.
Esto detecta, entre otros errores, `SystemExit(0)` prematuro. No es una prueba contra
código deliberadamente adversarial que inspeccione o manipule el propio verificador.
El código generado sigue ejecutándose solo en Docker aislado.

## Kev: aún no validado

CUDA 12.8 / PyTorch 2.8.0+cu128 ejecutó una operación real en la RTX 3060 Ti.
Sin embargo, el arranque Kev no ha cargado los pesos base y `/v1/models` no responde.
La prueba real registra `NOT_VALIDATED` y `ConnectError`, con cero inferencias.
No se confunde el éxito de CUDA con una inferencia Kev.

La descarga alternativa sigue en `runtime/kev-base.safetensors.partial`. Antes de
usar ese archivo debe alcanzar 1.746.942.600 bytes y su SHA256 debe ser
`c2b1e5a17d9c1e27685d92ed9b382911ebb99955ecd89052d1721241adfbab6c`.
La base corresponde a Qwen/Qwen3.5-0.8B-Base revisión
`dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68`. No se ha copiado a la caché en uso.
Una revisión automática bloqueó la orden de detener el arranque atascado y
reiniciar la descarga; se mantuvo el proceso y se descargó a una ruta independiente.

El nuevo validador exige que el servidor declare el checkpoint Kev fijado y CUDA,
valida respuestas tipadas y registra tiempos de tres clasificaciones reales.
La identidad declarada por el servidor no sustituye una atestación de los archivos.
El observador sigue sin controlar permisos ni rutas.

## Reproducción

```powershell
.venv/Scripts/python.exe -m hydra.training.regression_corpus
.venv/Scripts/python.exe -m hydra.training.evaluate_corpus --model hydra-q5-candidate --corpus data/hydra-regression-v2 --build-manifest models/hydra-q5/build-manifest.json --output data/evaluations/hydra-q5-regression-v2.json
.venv/Scripts/python.exe -m hydra.training.validate_local_engine
.venv/Scripts/python.exe -m hydra.training.validate_kev
```

Perfil experimental: `config/models.hydra-q5.yaml`. No cambia el perfil predeterminado.
Evidencia versionada en `docs/evidence`: `q4-q5-regression-v2.json`, los informes
individuales, `hydra-q5-pilot.json`, `q5-engine-before.json`, `q5-engine-live.json`
y `kev-live.json`.

Validación de código: 34 pruebas focalizadas superadas, incluidos kernel, fachada,
identidad del modelo, comparación, finalización del verificador y validador Kev
simulado. Ruff y `git diff --check` correctos. Las pruebas simuladas no acreditan
la disponibilidad de Kev. La suite completa no se repitió en este avance.
