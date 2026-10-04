# Entrada asíncrona unificada de HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

La API pública `hydra.engine.HydraEngine` es una fachada pequeña sobre el kernel
existente. No crea otro orquestador, instala LiteLLM ni duplica memoria, caché,
proveedores, permisos o verificadores. Reducir las líneas de la fachada no reduce
por sí mismo la memoria de los modelos ni convierte el runtime en ultraligero.

```python
import asyncio
from hydra.engine import HydraEngine
from hydra.core.config import Settings

async def main():
    # Usa el registro de modelos y endpoints configurado para tu instalación.
    async with await HydraEngine.create(Settings()) as engine:
        result = await engine.query(
            "Explica los requisitos del documento",
            context="Contenido real del documento ya extraído...",
        )
        print(result.answer)
        print(result.meta.models_used, result.meta.verified)

asyncio.run(main())
```

`local_only=True` es el valor predeterminado de `query`. El registro debe incluir
un backend local disponible. `Settings(offline=True)` permite pruebas con modelos
simulados y no acredita inferencia real. Para usar extensiones remotas debe
seleccionarse `local_only=False`; siguen aplicándose las políticas del kernel.

El resultado es `HydraResponse`, con respuesta, modelos utilizados, verificación,
incertidumbres, artefactos y confirmaciones pendientes. `result.model_dump()` lo
convierte a diccionario. No se inventa una latencia de Sistema 1 si no se midió.

`context` contiene texto real y se incorpora como material del usuario, nunca como
instrucción de sistema. `images` acepta las URI del contrato `Message` existente;
requiere un modelo visual compatible. Esta fachada no abre rutas, extrae PDF,
procesa audio ni resume automáticamente archivos de 500 páginas. La extracción,
selección y límites de contexto requieren su propia integración y medición.

`mode`, `use_cache`, `max_cost` y `max_latency_ms` se transmiten al kernel existente.
La caché sigue su política actual; no se crea una caché global de respuestas que
mezcle permisos o conversaciones. `execute(HydraRequest(...))` permite el contrato
completo, incluido historial y aprobaciones explícitas de acciones.

Se crea un runtime una vez y se reutiliza. El contexto asíncrono lo cierra incluso
si una consulta falla. `HydraEngine(runtime)` permite usar un runtime ya existente
sin apropiarse de su cierre. La cancelación se propaga. El llamador debe terminar
sus consultas activas antes de cerrar el runtime compartido.

## Qué se conserva y qué se corrige del ejemplo propuesto

- Se conserva el punto de entrada asíncrono y la separación entre decisión,
  contexto e inferencia, con contratos de HYDRA.
- `__init__` y `__name__` requieren dobles guiones bajos. Una cadena de contenido
  no admite `.get()`; las respuestas estructuradas necesitan validación.
- Pedir JSON a un generador no implementa el protocolo tipado de Kev. HYDRA ya
  tiene `/v1/systemone` y un observador experimental separado del generador.
- Un nombre de archivo interpolado no entrega los bytes de ese archivo al modelo.
- Una cadena de varias peticiones sigue siendo varias inferencias, aunque tenga
  una única función pública. No se prometen latencias de 100 ms ni ahorro de RAM
  por sustituir los SDK sin medir dependencias y ejecución.
- Kev sigue en observación: no decide permisos ni cambia la ruta hasta superar
  calibración y evaluación. No se incorporan identificadores de modelos externos
  del ejemplo como si se hubiera comprobado su disponibilidad.

Validación: 18 pruebas pasan entre la fachada y el observador, incluida llamada
al kernel offline, propagación de cancelación, cierre, privacidad por defecto
y conservación del contrato. Ruff sin errores. Esto no acredita calidad del GGUF.
