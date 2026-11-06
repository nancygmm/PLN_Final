# Pendientes del proyecto — Asistente Laboral GT (CC3103)

## ✅ Ya hecho

- Código completo del sistema (`laboral_rag/`): ingesta por artículo, búsqueda BM25 e híbrida, filtros por rol y vigencia, router, calculadora de prestaciones, guardrails, salida JSON validada, auditoría y LLM intercambiable.
- Interfaz web para la demo (`app/streamlit_app.py`) con botones para cada caso de demostración.
- Banco de 31 casos y script de evaluación (`eval/run_eval.py`).
- Suite de 13 pruebas de seguridad que genera la tabla del §10 (`eval/security_report.py` → `docs/pruebas_seguridad.md`).
- 20 pruebas unitarias que pasan (`tests/`).
- README con arquitectura, instalación, uso y borrador de la sección "Uso de IA".
- Anteproyecto llenado (`docs/Anteproyecto_Proyecto_Final_CC3103.docx`).
- Borrador del documento técnico (`docs/documento_tecnico_borrador.md`), completo salvo los resultados.
- Presentación de 15 minutos en Claude (13 diapositivas con notas), completa salvo los resultados marcados `[__]`.

## ⏳ Falta

### Persona 1 — Datos y sistema (empieza ya; las demás dependen de esto)
- [ ] Descargar a `data/raw/` con estos nombres exactos:
  - `codigo_de_trabajo.pdf` ← https://www.amsclae.gob.gt/wp-content/uploads/2026/08/10.-DECRETO-1441-CODIGO-DE-TRABAJO.pdf
  - `decreto_42_92_bono14.pdf` ← https://mcd.gob.gt/wp-content/uploads/2013/07/bono-14-decreto-42-92.pdf
  - `decreto_76_78_aguinaldo.pdf` ← buscar una copia oficial (opcional)
- [ ] Anotar en `data/sources.yaml` la versión del Código de Trabajo y la URL del Decreto 76-78.
- [ ] `pip install -r requirements.txt` y `python -m laboral_rag.ingest`.
- [ ] Revisar `data/index/ingest_report.json` y algunos fragmentos para confirmar que los artículos se separan bien.
- [ ] Confirmar que se descarga el modelo de embeddings y que funciona el modo híbrido.
- [ ] Elegir el LLM, configurarlo en `.env` (copiar de `.env.example`) y probar varias preguntas.
- [ ] Hacer commit y push, y avisar a las otras dos personas.

### Persona 2 — Evaluación y seguridad (cuando la Persona 1 termine)
- [ ] Llenar `expected_pages` en `eval/dataset.jsonl` con las páginas reales del PDF.
- [ ] Correr `python -m eval.run_eval --modes bm25 hybrid`.
- [ ] Ajustar `MIN_EVIDENCE_SCORE` en `.env` según los resultados y volver a correr.
- [ ] Calificar la fidelidad de las respuestas de 0 a 1 (con la Persona 3 como segundo evaluador).
- [ ] Analizar los casos que fallan y escoger 2 para la autopsia de fallos.
- [ ] Volver a correr `python -m eval.security_report` con los PDF y el LLM.
- [ ] Validar con alguien que sepa de derecho laboral el cálculo de la indemnización.
- [ ] Pasarle a la Persona 3 los resultados (`eval/results/.../summary.md` y `docs/pruebas_seguridad.md`).

### Persona 3 — Documentos y presentación (puede empezar ya)
- [ ] Ajustar las fechas del plan de trabajo en `docs/Anteproyecto_Proyecto_Final_CC3103.docx`.
- [ ] Pasar `docs/documento_tecnico_borrador.md` al formato de entrega (10 a 15 páginas).
- [ ] Llenar los **[PENDIENTE]** del documento técnico y los `[__]` de la presentación con los resultados de la Persona 2.
- [ ] Completar la tabla "Uso de IA" del README.
- [ ] Ser segundo evaluador en la calificación de fidelidad.

### Todos
- [ ] Ensayar la demo con `streamlit run app/streamlit_app.py` (los 6 casos de la diapositiva 7).
- [ ] Leer y entender todo el código: la defensa es individual.
