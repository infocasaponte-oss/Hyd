# Proceso de propiedad intelectual

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

1. **Registrar** la invención candidata: `hydra ip propose "Título" --problem … --mechanism … --feature F1 F2 …`.
2. **Medir el efecto técnico** con experimentos reproducibles (`ip_experiment`, cápsula con entorno, hashes y
   resultados) y `hydra ip effect INV --metric TTFT --baseline 821 --value 534 --unit ms`.
3. **Contribuciones** humanas y asistencia de modelos se registran por separado (nunca se asume que autor
   del commit = inventor).
4. **Prior art**: `hydra ip prior-art INV --reference REF-A:F1,F2` → matriz de características.
5. **Estado**: CANDIDATE → PRIOR_ART_REVIEW → PATENT_REVIEW → FILED / TRADE_SECRET / PUBLIC. Mientras no esté
   presentada o liberada, la Release Gate bloquea divulgaciones públicas.
6. **Paquete de evidencias** para el profesional: `hydra ip bundle INV` (descripción técnica, cronología,
   contribuciones, experimentos, efectos, matriz, licencias, BOMs, hashes y firma).

Los plazos legales (prioridad, fases nacionales) los introduce el asesor como datos; HYDRA no los calcula
ni decide patentabilidad o autoría. La verificación de integridad está en `hydra ledger verify`.
