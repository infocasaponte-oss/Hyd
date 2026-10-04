# Kev: inferencia real en GPU validada

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 30/09/2026. El arranque original terminó su descarga y cargó el checkpoint;
no fue necesario reemplazar la caché con la copia alternativa. Ambas copias de la
base tienen el SHA256 esperado. Se conserva la alternativa sin borrar archivos.

- Servidor local: `http://127.0.0.1:8009`, proceso 56512 al comprobarlo.
- Modelo: `jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e`.
- Backend declarado: torch, dispositivo CUDA, precisión bfloat16.
- GPU: NVIDIA GeForce RTX 3060 Ti. El proceso del servidor aparece en `nvidia-smi`.
- Base en caché: 1.746.942.600 bytes; SHA256
  `c2b1e5a17d9c1e27685d92ed9b382911ebb99955ecd89052d1721241adfbab6c`.

Se ejecutó `python -m hydra.training.validate_kev` contra el servidor real. Los
resultados pasaron la validación del contrato tipado y las tres etiquetas esperadas:

| Consulta | Resultado | Tiempo observado por el cliente |
|---|---|---:|
| Paquete roto y reembolso | refund | 1.580,8 ms |
| Error de contraseña | technical | 304,3 ms |
| Precio del plan anual | pricing | 320,0 ms |

Estado: `INFERENCE_COMPLETED`, 3/3 aciertos. La primera petición incluye costes
iniciales; estas tres medidas no son un benchmark de carga ni prueban latencia
inferior a 100 ms. Los logs avisan de implementaciones PyTorch de referencia por
ausencia de `causal_conv1d` y `flash-linear-attention`: funciona, con optimización
de rendimiento pendiente. No se instalaron dependencias adicionales en este paso.

Evidencias: [respuestas reales](evidence/kev-live-gpu.json) y
[identidad de pesos y proceso GPU](evidence/kev-gpu-identity.json).
El informe anterior `kev-live.json` se conserva como registro del intento fallido.

Esto valida disponibilidad e inferencia básica de Kev en GPU. No valida calibración,
estabilidad sostenida, memoria máxima ni decisiones sobre herramientas. Se mantiene
`approved=false` y el modo observador: el modelo no recibe autoridad para conceder
permisos ni cambiar el enrutamiento productivo. El servidor queda ejecutándose.
