# HYDRA Decision v2: compuerta de cobertura

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

La cabeza Kev validada solo cubre parte de las etiquetas del corpus v3. HYDRA
ahora incorpora una compuerta determinista previa al observador:

- `review`: producción, pagos irreversibles, acciones médicas y cambios de permisos.
- `security`: phishing, credenciales, exfiltración y comandos peligrosos.
- `privacy`: datos personales, anonimización y borrado de datos.
- `abstain`: entradas vacías, referencias sin contexto y peticiones ambiguas.

La compuerta devuelve una observación tipada de `hydra-policy-v2`, con probabilidad
1, y no llama a Kev. Estas etiquetas son resultados de política HYDRA, no una
predicción del checkpoint. `review` exige revisión posterior y `abstain` pide
contexto; ninguno concede permisos.

Las solicitudes restantes siguen pasando por Kev con opciones canónicas. Si Kev
falla, las reglas deterministas del router siguen siendo la decisión efectiva.
Para sustituir la compuerta por una cabeza Kev v2 se necesitan datos verificados,
test independiente y los umbrales de [PLAN_MEJORA_KEV.md](PLAN_MEJORA_KEV.md).

Ya existe un candidato de cabeza ligera HYDRA v2 entrenado con el split train y
las diez etiquetas. Sus resultados sintéticos no se consideran evidencia de
generalización; está documentado en `KEV_V2_CANDIDATO.md` y permanece fuera del
router por defecto.

Validación: 19 pruebas del gate, observador y canonicalización; Ruff correcto.

El calibrador separado ya puede cargarse desde `HYDRA_DECISION_CALIBRATOR_PATH`
(`Settings.decision_calibrator_path`). El runtime valida el formato y exige que
el manifiesto incluya el hash del dataset de calibración antes de usarlo. Sus
probabilidades solo enriquecen la observación; la ruta efectiva y la política
siguen siendo deterministas.
