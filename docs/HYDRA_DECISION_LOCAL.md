# HYDRA-Decision: integración local en preparación

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Cambios implementados

`hydra.providers.decision` define una interfaz independiente de la generación de texto y un cliente local compatible con `/v1/systemone`. Valida Choice, Noul y Score: identificadores, probabilidades finitas, suma de distribuciones, opción seleccionada y coherencia de la puntuación. Rechaza endpoints remotos, proxies de entorno y redirecciones. Un error o timeout no se convierte en una decisión aprobada. El cliente todavía no está conectado al router del motor: no cambia sus permisos ni su selección actual.

El alias devuelto se contrasta con el solicitado; no constituye una prueba criptográfica de identidad del checkpoint. La revisión del código y del modelo se fija en el lanzador de prueba. Antes de integrar producción falta contrastar la información de `/v1/models`, los hashes de los archivos cargados y la política de admisión del proveedor.

Corregidos tres problemas de preparación de datos:

- El exportador de especialistas/enrutamiento exige `verified is True` aunque se reduzca la confianza mínima.
- El crítico omite respuestas no verificadas; ya no las etiqueta automáticamente como fallos. Por ahora solo exporta positivos verificados. Los negativos requieren incorporar resultados explícitos de verificadores a las trazas.
- El clasificador no sustituye la validación ausente por la precisión de entrenamiento: informa `validation_status=not_evaluated` y no publica `valid_accuracy`.

Esto no completa la fase de admisión: todavía falta imponer permisos de entrenamiento, procedencia por ejemplo, verificador independiente y separación de datasets en todos los exportadores.

Validación de esta implementación: suite completa **403 passed, 5 skipped** en 236,61 segundos. Ruff, cabeceras de licencia, espacios y sintaxis del lanzador PowerShell comprobados. Los skips no cuentan como evidencia de funcionamiento.

## Entorno Kev

- Código aislado: `runtime/kev`, commit `0c142becde423a0c68ec857f7831dac0315588a1`.
- Python aislado: `runtime/kev-env`; no reutiliza `.venv` del generador.
- Checkpoint de ensayo: `jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e`.
- Caché de pesos: `runtime/kev-cache`.
- Arranque: `scripts/start_kev_local.ps1`, limitado a `127.0.0.1:8009`.

```powershell
.\runtime\kev-env\Scripts\python.exe -m pip install --index-url https://pypi.org/simple './runtime/kev[serve]'
.\runtime\kev-env\Scripts\python.exe -m pip check
.\scripts\start_kev_local.ps1
```

La instalación inicial no es un lock transitivo: guardar `pip freeze` tras la instalación para reproducir ese entorno. El primer arranque descarga la base y el adaptador; arrancar el proceso no demuestra que el servidor esté listo. El lanzador actual exige CUDA y usa BF16 por defecto; `-CpuOnly` selecciona FP32 explícitamente. No atribuirle rendimiento CUDA si el paquete instalado funciona en CPU.

Resultado de instalación local: importación de Kev correcta, `pip check` sin incompatibilidades. PyTorch instalado: **2.8.0+cpu**, `CUDA=False`; esta prueba no utiliza la RTX 3060 Ti. Inventario de versiones guardado en `runtime/kev-environment.txt`. El lanzador admite los archivos no versionados de compilación que crea pip, pero sigue rechazando modificaciones a archivos versionados del checkout fijado. Logs de arranque: `runtime/kev-server.stdout.log` y `runtime/kev-server.stderr.log`; PID en `runtime/kev-server.pid`. La disponibilidad se comprueba con `GET http://127.0.0.1:8009/v1/models`, no por la mera existencia del proceso.

El checkpoint 0.8B es solo un ensayo de clasificación documental no crítica: su ficha desaconseja el enrutamiento de herramientas. Para aceptar un backend son necesarias pruebas reales de español, calibración, abstención, memoria y estabilidad. Las pruebas unitarias actuales utilizan transporte HTTP simulado, no certifican inferencia Kev.

## P1: observación experimental integrada

El router incorpora un observador opcional después de aplicar su política. Su salida
`RoutingDecision.observation` tiene versión 1, estado, alias de modelo, categoría,
distribución, confianza y tiempo. Viaja en los eventos existentes `route.selected`
y las trazas. No modifica la ruta, los permisos, la verificación ni las etiquetas
de entrenamiento. La confianza reportada todavía no está calibrada por HYDRA.

Desactivado por defecto. Para un ensayo con un servidor local ya verificado:

```powershell
$env:HYDRA_DECISION_SHADOW_ENDPOINT = 'http://127.0.0.1:8009'
$env:HYDRA_DECISION_SHADOW_MODEL = 'kev-latest'
$env:HYDRA_DECISION_SHADOW_TIMEOUT_S = '0.5'
```

El alias debe coincidir con el servidor. Solo admite un origen HTTP de loopback.
En modo offline no se construye el cliente. Las solicitudes privadas/local_only,
FAST o con presupuesto explícito de latencia omiten la observación. Se envía solo
el último texto del usuario; no se incluyen mensajes de sistema, imágenes ni historial.
En el resto, el experimento añade como máximo el plazo configurado más el tiempo
de cancelación del transporte (0,5 s por defecto; máximo configurable 5 s).

Una respuesta inválida, un error HTTP o un timeout conserva la decisión original
y registra el tipo de fallo, sin copiar texto del servidor. La cancelación de la
solicitud se propaga. El cierre del runtime libera el cliente HTTP.

Las pruebas de contrato usan HTTP simulado: contradicción de categoría, privacidad,
presupuesto, errores, timeout, cancelación y desconexión offline. Todavía faltan
calibración independiente, abstención aprendida y comparación con reglas; esta
integración no habilita Kev como decisor de herramientas ni completa P1.

Durante la regresión se detectó otra incompatibilidad: con `pyarrow` instalado,
el corpus exporta Parquet y el clasificador intentaba abrirlo como JSONL UTF-8.
El lector ahora admite ambos formatos y decodifica las columnas JSON del corpus.
Una prueba compara las mismas etiquetas y texto español en ambos formatos;
el entrenamiento real del clasificador vuelve a pasar su prueba de integración.

Validación de este avance: **425 passed, 5 skipped** en 202,41 segundos;
Ruff y `git diff --check` sin errores. Los cinco skips y las pruebas con HTTP
simulado no acreditan disponibilidad de Kev. La suite anterior detectó la
incompatibilidad Parquet; el resultado indicado corresponde a la repetición
completa después de corregirla.
