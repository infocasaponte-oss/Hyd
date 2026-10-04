# Kev: fiabilidad del código y acceso web de HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Cambios de Kev implementados

Se auditó la ruta de carga, entrenamiento, cabeza de decisión y API del checkout fijado en `0c142becde423a0c68ec857f7831dac0315588a1`. Los cambios están en un worktree separado, `runtime/kev-hydra`, rama `codex/hydra-kev-reliability`; el checkout original permanece intacto. El parche reproducible está en `patches/kev/hydra-reliability-v1.patch`, con SHA256 y archivos individuales en `patches/kev/manifest.json`.

1. Las distribuciones Choice/Score conservan sus probabilidades originales; antes se redondeaban a cuatro decimales y las probabilidades pequeñas desaparecían antes de calibrar. La normalización de logits usa FP32. Los campos y escalares de la API mantienen su contrato.
2. Se rechazan distribuciones inválidas, valores no finitos y diferencias de longitud entre salidas y preguntas.
3. El adaptador se comprueba contra base, revisión y arquitectura antes de cargar el modelo base. Un valor por defecto incompatible deja de provocar una descarga o carga inútil antes del rechazo.
4. El entrenamiento personalizado rechaza registros marcados como test/calibración/validación o `training_allowed=false`, elimina duplicados exactos y rechaza etiquetas contradictorias para una misma petición. No se modificaron particiones congeladas.
5. Se corrigieron dos errores de Windows: formato de fecha `%-d` y rutas con barras invertidas en los nombres enviados a Hugging Face.
6. Las peticiones con varias preguntas se procesan secuencialmente por pregunta. En este checkpoint BF16, el test real encontró una diferencia de aproximadamente 0,023 al agrupar una pregunta con otra. La prueba de aislamiento pasó después del cambio. El coste es más inferencias por petición múltiple; el router de HYDRA usa una sola pregunta y no añade ese coste.

La API indica `probability_format=float32-unrounded-v1` y `question_execution=separate-sequential-v1`. Se mantiene la política determinista para permisos y decisiones críticas.

## Evidencia y límites

| Comparación sobre las mismas 100 paráfrasis conocidas | Original | Precisión numérica corregida |
| --- | ---: | ---: |
| Aciertos | 77/100 | 77/100 |
| Temperatura ajustada solo en calibración | 4 | 3 |
| NLL | 0,66061 | 0,61898 |
| ECE | 0,03776 | 0,04982 |

La corrección numérica no aumentó los aciertos. La NLL mejoró y la ECE empeoró ligeramente: no se presenta como mejora universal de calidad. Las confusiones semánticas siguen requiriendo ejemplos diversos y una nueva evaluación independiente. No se habilitó control autónomo ni se promocionó el modelo.

- Paridad de entrenamiento en GPU: cuatro ejemplos de desarrollo admitidos, cuatro pasos y semilla 42; **376 tensores idénticos**, diferencia máxima cero entre código original y modificado.
- API real y pruebas nuevas de fiabilidad: **18 superadas**, incluida la prueba de preguntas agrupadas tras corregirla.
- Pruebas de pérdidas, permutación, anclas, generación contrastiva y guardas: **27 superadas**.
- Pruebas unitarias upstream centradas en el contrato API y caché: **14 superadas**.
- No se certificó toda la batería upstream: hay pruebas que requieren checkpoints, particiones remotas, Modal y un entorno POSIX. Los primeros intentos identificaron archivos ausentes del checkout reducido y dependencias no instaladas; se conservan los registros. No se cambiaron umbrales de pruebas para hacerlas pasar.
- HYDRA: batería completa **525 superadas, 5 omitidas**; después, **27 pruebas enfocadas** comprobaron los ajustes recientes de web y autoridad.

Evidencias: `docs/evidence/kev-training-patch-parity.json`, `docs/evidence/kev-hydra-v2-r1-precision-regression.json`; registro general `runtime/hydra-kev-web-tests.log`.

Para verificar o reconstruir el fork desde el checkout original instalado:

```powershell
.venv/Scripts/python.exe -m scripts.prepare_kev_reliability_fork
runtime/kev-env/Scripts/python.exe -m scripts.serve_kev_candidate --run models/kev-hydra-v2-r1 --port 8009 --source-root runtime/kev-hydra
```

## Acceso web sin claves de pago

Se implementaron `web.search` y `web.read`, con AsyncIO, HTTPX y el parser HTML estándar de Python. No hay SDK de búsqueda de pago, claves de Google/Brave ni dependencia de LangChain.

- Motores por URL: Google, Brave, Bing y DuckDuckGo. Si el motor solicitado bloquea o no proporciona resultados HTML utilizables, se intenta una alternativa. Si ninguna funciona, se devuelven los enlaces para abrir la búsqueda en un navegador; no se eluden CAPTCHAs.
- Opera es un navegador: puede abrir los mismos enlaces. No se presenta como un motor de búsqueda adicional ni se ha automatizado su instalación o interfaz.
- Lectura directa de URLs HTTP(S) públicas, extracción de texto y fuentes citables. En esta versión no se ejecuta JavaScript ni se extraen PDFs o páginas que exijan iniciar sesión.
- Se verifica y fija una IP pública conservando Host y SNI TLS; cada redirección se vuelve a validar. Se excluyen credenciales en la URL, redes privadas, puertos no estándar, respuestas demasiado grandes y contenido binario.
- La herramienta respeta modo privado/offline, permisos del worker y presupuesto. El contenido externo se marca como no confiable y no concede permisos ni entra automáticamente en entrenamiento.
- Una solicitud explícita de consultar la web activa la recuperación aunque el clasificador la confunda con programación. El motor adjunta solo fuentes que realmente leyó con HTTP 200; buscar enlaces no equivale a verificar una afirmación.

Configuración explícita para otras instancias: `HYDRA_PUBLIC_WEB_ENABLED=true`, con modo offline desactivado. Se habilitó en el Studio experimental; no se cambió CeltIA.

## Studio y prueba real

URL: `http://127.0.0.1:18084/studio`. Recargar para ver la pestaña **Web**.

1. En **Web**, introducir una consulta y seleccionar Google, Brave, Bing o DuckDuckGo.
2. En **Leer una URL**, introducir una página pública y pulsar **Leer página**.
3. En **Chat**, probar: `Investiga en la web qué es asyncio usando https://docs.python.org/3/library/asyncio.html . Responde en una frase y cita esa URL.`

La prueba real devolvió HTTP 200, `tools_used=[web.read]`, respuesta del GGUF 1.5B y fuente adjunta; 1,43 segundos en esa llamada. La respuesta conserva `verified=false`: leer la fuente no certifica toda la generación.

Brave respondió 429 en la prueba y la alternativa DuckDuckGo devolvió cinco resultados. La lectura de documentación Python devolvió 200. La petición desde el endpoint de Studio seleccionando Google también recurrió a DuckDuckGo, sin API de pago.

Endpoints autenticados con las mismas reglas del gateway:

```text
POST /hydra/v1/web/search {"query":"...","engine":"google","limit":5}
POST /hydra/v1/web/read   {"url":"https://..."}
```

Pruebas reproducibles: `scripts/validate_public_web.py`, `scripts/validate_web_chat.py`. Evidencia en `docs/evidence/public-web-live-2026-09-30.json`, `studio-web-search-live.json` y `studio-web-chat-live.json`.

## Siguiente mejora de precisión

Ampliar el desarrollo con pares contrastivos variados de herramienta/análisis, petición completa/incompleta y acción reversible/irreversible. Seleccionar recetas por desarrollo separado, recalibrar y mantener el test conocido como regresión. La promoción debe esperar un test humano nuevo y congelado, con precisión y cobertura suficientes; las mejoras de código de esta ronda no sustituyen ese requisito.
