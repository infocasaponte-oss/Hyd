# Revisión de la integración de Claude — 2026-09-29

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Revisión local de `integration/hydra-1.0` en `500e9918da25e30efa3c03e318012aad1eb9889f`, contrastada con el repositorio remoto. La integración conserva ambos historiales, incorpora `hydra.runtime`, monta su API y conecta captura, verificación y despliegue. Su CI pasó. Esto acredita la integración del código; no acredita un modelo HYDRA entrenado ni un despliegue físico evaluado.

## Correcciones implementadas

1. **Autenticación del enrutamiento.** La ruta de tareas ejecutaba `kernel.prepare` y escribía eventos sin comprobar la clave del gateway. Ahora comprueba autenticación y límite de peticiones antes de preparar la tarea. Una regresión reproduce el acceso anónimo anterior y comprueba que devuelve 401 sin escribir eventos.
2. **Destino de inferencia del GGUF.** El puente generaba variantes sin `endpoint` ni `served_model`; el cliente físico no podía utilizarlas. Ambos campos son ahora obligatorios y viajan en los metadatos. Se acepta un endpoint HTTP local sin credenciales, consulta ni fragmento. La prueba comprueba el destino y el nombre del modelo mediante transporte simulado; no demuestra que un servidor real esté sirviendo esos pesos.
3. **Evidencia de pruebas del planificador.** Una ejecución parcial podía sustituir el resultado de la suite completa. Ahora ambas evidencias se separan, un parche invalida el resultado anterior y los cambios Python requieren una nueva suite completa satisfactoria para finalizar como logrados. Se cubren la suite fallida seguida de pruebas parciales verdes y la invalidación tras un parche.
4. **Sandbox predeterminado.** Configuración y herramienta usaban `python:3.12-slim`, frente al `hydra-sandbox:py312-v3` documentado por el runtime. Los valores predeterminados coinciden ahora. La imagen debe estar construida localmente para ejecutar tareas Docker.

El CLI del puente requiere ahora, además de los argumentos anteriores:

```powershell
python -m hydra.model_factory.deploy_bridge models/hydra-pilot --benchmark bench.json --capability coding --endpoint http://127.0.0.1:11434/v1 --served-model hydra-local
```

Este comando prepara el cuerpo de registro; no levanta el servidor, no verifica la identidad de sus pesos y no activa automáticamente el despliegue.

## Validación

- Antes de las correcciones: **372 passed, 5 skipped**.
- Después: `py -3.12 -m pytest -q --tb=short`: **380 passed, 5 skipped**.
- `py -3.12 -m ruff check .`: correcto.
- `git diff --check`: correcto.

Las pruebas omitidas no se consideran evidencia de funcionamiento. Las pruebas del puente usan inferencia simulada. Las correcciones se realizan en la rama aislada `codex/review-claude-integration` para no interferir con el checkout de trabajo de Claude.

## Pendiente para conseguir HYDRA.gguf

1. Completar y verificar el modelo base fijado en `config/recipes/hydra-pilot.json`. El archivo local `D:\HYDRA\models\base\model.safetensors.partial` contiene **22.544.410 bytes** frente a **3.087.467.144** esperados: no permite entrenar todavía.
2. Ejecutar entrenamiento con el corpus HYDRA verificado, fusión, conversión y cuantización mediante la factoría existente. Conservar manifiestos y hashes de cada etapa. El corpus de 192/32/64 ejemplos es un piloto sintético limitado; ampliarlo con familias de tareas independientes antes de concluir calidad general.
3. Evaluar el candidato real sobre tareas reservadas y medir calidad, TTFT, tokens/s y memoria. Vincular los resultados al hash del GGUF. Comparar con el baseline sin reutilizar los datos de entrenamiento como prueba independiente.
4. Servir ese mismo artefacto, comprobar su identidad y la inferencia física a través del motor; pasar las puertas de promoción, shadow, canary y activación con evidencia real y rollback comprobado.

`HYDRA-baseline.gguf` es una referencia Qwen exportada, no un modelo especializado por HYDRA. El GGUF diminuto de `data/training-smoke` solo prueba la mecánica del pipeline con pesos aleatorios. Ninguno sustituye el candidato final. El resultado previo 64/64 del baseline corresponde a un conjunto pequeño y no demuestra capacidad general.

No se ha fusionado a `main`, publicado una versión ni modificado la visibilidad o protección del repositorio durante esta revisión.
