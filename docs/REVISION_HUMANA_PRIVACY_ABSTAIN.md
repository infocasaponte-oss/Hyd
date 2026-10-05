# Corrección humana desde el navegador

La herramienta local abre el paquete privado generado por `decision_label_audit`.
Muestra texto original y todas las rutas, con etiqueta anterior y predicciones
ocultas. Escribe quién revisa, escoge una etiqueta y pulsa **Gardar e seguinte**.
**Precisa aclaración** exige una nota y no admite automáticamente el caso.

```powershell
D:\HYDRA\.venv\Scripts\python.exe -m hydra.api.label_audit_app --root D:\hyd-train-v6\out\review-privacy-abstain-20261005 --port 8091
```

Abre `http://127.0.0.1:8091`. Funciona en este equipo; el enlace localhost no
permite acceso desde otro ordenador. No se publica el corpus ni se crea acceso
remoto. La identificación del revisor es una declaración local, no una cuenta
autenticada. El servidor solo escucha en loopback y exige un token por sesión
para guardar; no admite nombres de host externos.

Las revisiones quedan en `human-reviews.sqlite3` junto al paquete, como eventos
añadidos sin borrar los anteriores. Reiniciar conserva el trabajo. La vista
**Todas, incluídas as revisadas** permite volver a un caso y registrar otra
decisión. **Exportar revisións JSONL** descarga el historial portable, con texto,
hash, revisor, etiqueta y fecha. Conserva datos privados: no subirlo al repositorio.

El corpus original, los tests y los candidatos permanecen intactos. Este servidor
no aplica correcciones al corpus ni inicia entrenamiento. La próxima versión del
corpus necesita adjudicación humana de esas revisiones y conservación del historial.

Verificado con fixture sintética: guardado, rechazo de POST sin token y de host
externo, nota obligatoria en ambiguos, historial exportado, original intacto y
persistencia tras reinicio. Las preguntas reales no recibieron etiquetas de prueba.
