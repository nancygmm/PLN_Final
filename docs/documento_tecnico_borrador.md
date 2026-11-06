# Asistente Laboral GT: sistema RAG agéntico de consulta de normativa laboral guatemalteca con cálculo de prestaciones

**Documento técnico (borrador)** · CC3103 Procesamiento de Lenguaje Natural · Universidad del Valle de Guatemala · 2026
Integrantes: Nancy Mazariegos, Santiago Pereira, Brandon Reyes, Hugo Rivas

> Las marcas **[PENDIENTE]** indican datos que se completan al correr el sistema con los PDF reales (`python -m eval.run_eval` y `python -m eval.security_report`).

---

## 1. Resumen ejecutivo

Las dudas laborales más comunes en Guatemala (vacaciones, aguinaldo, Bono 14, período de prueba, indemnización) se resuelven hoy buscando en PDF extensos del Código de Trabajo, en fuentes no oficiales o preguntando repetidamente a Recursos Humanos. Los chatbots genéricos responden con seguridad, pero sin citas, sin distinguir versiones vigentes y con errores aritméticos al estimar montos.

Asistente Laboral GT es un sistema NLP/RAG agéntico que recupera artículos de fuentes oficiales autorizadas, genera respuestas fundamentadas que citan fuente, página y fragmento, se abstiene cuando no hay evidencia y delega los cálculos de prestaciones a una herramienta determinista. Integra control de acceso por rol, filtrado por vigencia documental, guardrails de entrada, contexto y salida, y un registro de auditoría con datos personales redactados.

Se evaluó con un banco de 31 casos y 13 pruebas adversarias, comparando una línea base léxica (BM25) contra una recuperación híbrida (BM25 + embeddings con Reciprocal Rank Fusion). Resultados principales: Recall@5 de **[PENDIENTE]** frente a **[PENDIENTE]** de la línea base, precisión de citas de **[PENDIENTE]**, abstención correcta en **[PENDIENTE]** de los casos sin respuesta y **[PENDIENTE]** de los ataques controlados.

## 2. Problema

**Situación actual.** La normativa laboral está dispersa en el Código de Trabajo (Decreto 1441 y reformas) y en leyes complementarias como el Decreto 42-92 (Bono 14) y el Decreto 76-78 (aguinaldo). Se publica en PDF largos, sin búsqueda semántica y sin indicar con claridad qué versión está vigente.

**Dolor.** Encontrar el artículo que responde una duda concreta, entenderlo y estimar montos sin errores. Los errores más frecuentes son de proporcionalidad: periodos de cómputo distintos (1 de diciembre a 30 de noviembre para el aguinaldo; 1 de julio a 30 de junio para el Bono 14) y cálculo por días.

**Impacto.** Para el colaborador, desconocer sus derechos o aceptar montos incorrectos. Para la empresa, tiempo de RR.HH. en consultas repetitivas, reclamos, demandas y riesgo de sanciones de la Inspección General de Trabajo.

**Hipótesis.** Un sistema que (1) segmenta la ley por artículo, (2) combina búsqueda léxica y semántica, (3) obliga a citar evidencia o abstenerse y (4) calcula montos con una herramienta determinista responde con mayor exactitud y verificabilidad que un LLM sin recuperación, con un costo de operación bajo.

**Criterio de éxito.** Recall@5 ≥ 0.80, precisión de citas ≥ 0.90, abstención correcta ≥ 0.90, bloqueo de ataques ≥ 0.95 y latencia P95 ≤ 6 s.

## 3. Perfiles de usuario

| Usuario | Necesidad | Permisos | Riesgo de error |
|---|---|---|---|
| Colaborador (primario) | Consultar derechos y estimar aguinaldo, Bono 14 y vacaciones | Rol `colaborador`: solo fuentes públicas | Medio-alto: reclamar o aceptar montos incorrectos |
| Analista de RR.HH. (secundario) | Responder consultas, verificar artículos, consultar políticas internas, estimar liquidaciones | Rol `rrhh`: fuentes públicas y políticas internas | Alto: una indemnización mal calculada genera pérdidas o demandas |

El rol lo asigna la sesión (en producción, el sistema de autenticación), nunca el texto de la consulta.

## 4. Caracterización de fuentes

| Fuente | Formato | Propietario | Versión | Actualización | Acceso | Sensibilidad |
|---|---|---|---|---|---|---|
| Código de Trabajo (Decreto 1441 y reformas) | PDF | Congreso de la República | **[PENDIENTE: edición]** | Al aprobarse reformas | colaborador, rrhh | Pública |
| Decreto 42-92 (Bono 14) | PDF | Congreso de la República | 1992 | Eventual | colaborador, rrhh | Pública |
| Decreto 76-78 (aguinaldo) | PDF | Congreso de la República | 1978 | Eventual | colaborador, rrhh | Pública |
| Política Interna de Personal v2026 (ficticia) | Markdown | Equipo (sintética) | 2026-1 (vigente) | Anual | rrhh | Privada |
| Política Interna de Personal v2024 (ficticia) | Markdown | Equipo (sintética) | 2024-1 (derogada) | — | rrhh | Privada |

**Gobernanza.** Todas las fuentes se declaran en un inventario versionado (`data/sources.yaml`) con URL, propietario, licencia, versión, frecuencia de actualización, sensibilidad, roles y vigencia. El pipeline solo indexa lo declarado. Las leyes son normas jurídicas de carácter público. Las políticas internas son documentos sintéticos de una empresa inventada, creados para demostrar permisos y versionado sin usar información confidencial real. Los PDF de terceros no se redistribuyen en el repositorio.

**Estadísticas del corpus.** **[PENDIENTE: copiar de `data/index/ingest_report.json` — páginas, fragmentos y artículos por fuente]**

## 5. Estado del arte

**Retrieval-Augmented Generation (RAG).** Lewis et al. (2020) proponen condicionar la generación de un modelo de lenguaje en documentos recuperados de una memoria no paramétrica, lo que mejora la factualidad y permite actualizar el conocimiento sin reentrenar. Es la base de este sistema: el LLM solo redacta a partir de los fragmentos recuperados.

**Recuperación léxica.** BM25 (Robertson y Zaragoza, 2009) puntúa documentos por frecuencia de términos con saturación y normalización por longitud. Sigue siendo una línea base fuerte, en especial para identificadores exactos como “artículo 82” o “Decreto 42-92”, que los modelos densos tienden a representar mal.

**Recuperación densa.** Sentence-BERT (Reimers y Gurevych, 2019) produce embeddings de oraciones comparables por similitud coseno; su extensión multilingüe por destilación (Reimers y Gurevych, 2020) permite usarlo en español. Captura paráfrasis (“¿me pagan algo si me quedo más tarde?” ↔ “jornada extraordinaria”) que BM25 no encuentra.

**Fusión híbrida.** Reciprocal Rank Fusion (Cormack et al., 2009) combina rankings sumando 1/(k + rango), sin calibrar escalas de puntuación distintas. Es simple, robusta y suele superar a cada método por separado.

**Agentes y herramientas.** Los sistemas agénticos delegan subtareas a herramientas externas. Aquí el agente es deliberadamente acotado: un router determinista decide entre recuperación y una única herramienta de cálculo, con límites de llamadas y sin capacidad de ejecutar acciones con efectos.

**Seguridad en aplicaciones con LLM.** Greshake et al. (2023) muestran que la inyección indirecta (instrucciones ocultas en el contenido recuperado) compromete aplicaciones reales. El OWASP Top 10 para aplicaciones LLM incluye inyección de prompt, divulgación de información sensible, manejo inseguro de salidas y agencia excesiva, riesgos que este sistema mitiga explícitamente.

**Evaluación de RAG.** RAGAS (Es et al., 2024) propone métricas de fidelidad, relevancia de la respuesta y precisión y exhaustividad del contexto. Este trabajo usa métricas de recuperación clásicas (Recall@k, MRR) junto con fidelidad evaluada por rúbrica y métricas de comportamiento (abstención, bloqueo).

## 6. Arquitectura

### 6.1 Flujo de consulta

```
consulta + rol
  → guardrails de entrada (inyección, acción crítica, longitud)
  → router de intención (consulta | cálculo | fuera de dominio)
      consulta → recuperación híbrida filtrada por rol y vigencia
               → filtro de contexto (inyección indirecta)
               → compuerta de evidencia (abstención)
               → generación estructurada (LLM o extractiva)
      cálculo  → extracción y validación de parámetros → calculadora → base legal citada
  → guardrails de salida (citas válidas, fuga de prompt, esquema)
  → RAGResponse JSON + registro de auditoría (PII redactada)
```

### 6.2 Flujo de ingesta

`PDF/MD → extracción (pypdf) → limpieza (normalización Unicode, guiones de corte, encabezados y pies repetidos, números de página) → chunking por artículo → metadatos y versión → índice BM25 + matriz de embeddings`

### 6.3 Componentes

| Componente | Archivo | Decisión de diseño |
|---|---|---|
| Ingesta | `laboral_rag/ingest.py` | El artículo es la unidad semántica y de cita natural de una ley. Los artículos de más de 1,800 caracteres se subdividen con 200 de solapamiento |
| Recuperación | `laboral_rag/retrieval.py` | BM25 + denso con RRF (k = 60). Filtro de rol y vigencia antes de puntuar. Refuerzo al artículo citado explícitamente |
| Router y orquestación | `laboral_rag/agent.py` | Reglas deterministas y explicables; estado compartido en `Trace`; una llamada a herramienta por consulta |
| Calculadora | `laboral_rag/tools/prestaciones.py` | La aritmética de fechas no se delega al LLM |
| Generación | `laboral_rag/llm.py` | Proveedor intercambiable; modo extractivo como línea base sin costo |
| Guardrails | `laboral_rag/guardrails.py` | Defensa en profundidad: entrada, contexto, salida y logs |
| Contratos | `laboral_rag/schemas.py` | Pydantic para fragmentos, salida y casos de prueba |

### 6.4 Esquema de un fragmento

`chunk_id, text, source, page, version, title, article, access, vigente, hash`

### 6.5 Contrato de salida

`answer` (string), `sources` (lista de fuente, página y chunk_id), `abstained` (bool), `tool_used` (string o null), `needs_human_review` (bool). Validado con Pydantic; las citas que no corresponden a fragmentos recuperados se eliminan.

### 6.6 Decisiones de recuperación

- **Por qué híbrida.** Las consultas mezclan identificadores exactos (“artículo 14 bis”, “FRM-RH-11”), donde BM25 es superior, con paráfrasis coloquiales, donde los embeddings son superiores.
- **Modelo de embeddings.** `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensiones): multilingüe, ligero y ejecutable en CPU.
- **Sin base vectorial.** Con menos de 2,000 fragmentos, la búsqueda exacta por producto punto en NumPy es instantánea; una base vectorial agregaría complejidad sin beneficio.
- **Abstención.** Se abstiene si la evidencia del mejor fragmento (máximo entre cobertura léxica y similitud coseno) es menor a 0.15, si el LLM declara evidencia insuficiente o si la respuesta queda sin citas válidas. Con evidencia menor a 0.30 activa `needs_human_review`.

### 6.7 Herramienta

`calculadora_prestaciones(concepto, salario_mensual, fecha_inicio, fecha_fin, salario_promedio_6m?, vacaciones_gozadas_dias?, incluir_sextas?)`

| Concepto | Fórmula | Base legal |
|---|---|---|
| Aguinaldo | salario × días en el periodo (1 dic – 30 nov) / 365 | Decreto 76-78 |
| Bono 14 | salario × días en el periodo (1 jul – 30 jun) / 365 | Decreto 42-92 |
| Vacaciones | (salario / 30) × (15 × días / 365 − días gozados) | Código de Trabajo, arts. 130 y 133 |
| Indemnización | base × días / 365; base = promedio de 6 meses × (1 + 2/6) si se incluyen sextas partes | Código de Trabajo, art. 82 |

Validaciones previas: salario entre Q0 y Q500,000, fecha de fin posterior a la de inicio y relación laboral menor a 60 años. La indemnización siempre activa revisión humana.

## 7. Banco de pruebas

31 casos en `eval/dataset.jsonl` con los campos `id, question, expected_behavior, expected_sources, expected_pages, answerable, risk_level` (y además `expected_articles, category, role`).

| Categoría | Casos | Ejemplo |
|---|---|---|
| Directas | 5 | ¿Cuántos días de vacaciones corresponden por año? |
| Paráfrasis | 3 | Si me quedo más tiempo del horario, ¿me pagan algo adicional? |
| Identificadores exactos | 3 | ¿Qué dice el artículo 14 bis? |
| Compuestas | 3 | Causas justas de despido y monto de indemnización |
| Ambiguas | 2 | ¿Cuánto me toca? |
| Sin respuesta | 2 | Salario mínimo 2026 |
| Dependientes de versión | 2 | Teletrabajo en la política vigente y en la versión 2024 |
| Herramienta | 6 | Cálculo nominal, selección errónea, parámetros fuera de rango, revisión humana, acción crítica |
| Seguridad | 5 | Inyección directa, evasión de permisos, alucinación forzada |

## 8. Análisis de métricas

### 8.1 Resultados comparativos

**[PENDIENTE: pegar `eval/results/<fecha>/summary.md`]**

| Métrica | Meta | BM25 (línea base) | Híbrida |
|---|---|---|---|
| Recall@5 | ≥ 0.80 | | |
| MRR | ≥ 0.65 | | |
| Ruido de contexto | — | | |
| Precisión de comportamiento | ≥ 0.85 | | |
| Precisión de citas | ≥ 0.90 | | |
| Abstención correcta | ≥ 0.90 | | |
| Bloqueo de ataques | ≥ 0.95 | | |
| Latencia media / P95 (ms) | P95 ≤ 6,000 | | |
| Llamadas al LLM / tokens | ≤ 3 por consulta | | |

### 8.2 Fidelidad

**[PENDIENTE]** Dos integrantes califican cada respuesta respondible de 0 a 1 (1 = todas las afirmaciones están respaldadas por los fragmentos citados). Reportar el promedio y el acuerdo entre evaluadores.

### 8.3 Análisis por categoría

**[PENDIENTE]** Comparar el Recall@5 por categoría. Hipótesis a verificar: BM25 rinde mejor en identificadores exactos y la búsqueda híbrida en paráfrasis.

### 8.4 Autopsia de fallos

**[PENDIENTE: elegir 2 o 3 casos fallidos]** Para cada uno: consulta, comportamiento esperado y observado, causa raíz (extracción, chunking, recuperación, umbral o generación) y corrección propuesta o aplicada con su efecto medido.

## 9. Auditoría de seguridad

Suite adversaria reproducible: `python -m eval.security_report` → `docs/pruebas_seguridad.md`.

| Amenaza | Componente | Mitigación |
|---|---|---|
| Inyección directa (español e inglés, cambio de rol) | Entrada | Patrones normalizados sin tildes; eliminación de caracteres invisibles; respuesta genérica |
| Inyección indirecta / envenenamiento de fuente | Contexto | Se descartan fragmentos con instrucciones antes de generar; el prompt trata el contexto como datos |
| Evasión de permisos | Recuperación | Filtro por rol antes de puntuar; el rol no se toma del texto |
| Acciones críticas | Router | Detección y escalamiento humano; ninguna herramienta tiene efectos |
| Alucinación forzada | Generación | Restricción al contexto, validación de citas y abstención |
| Abuso de herramientas | Calculadora | Validación de rangos y una llamada por consulta |
| Fuga de datos personales | Auditoría | Redacción de DPI, correo, teléfono y NIT |
| Indisponibilidad del LLM | Generación | Degradación al modo extractivo |

**Resultados:** **[PENDIENTE: resultado de la suite con el corpus completo]**

## 10. Limitaciones operativas

- La calidad depende de la extracción del PDF: tablas, notas al pie o columnas pueden romper la segmentación por artículo.
- Los guardrails de inyección se basan en patrones; ataques parafraseados o en otros idiomas pueden evadirlos (defensa en profundidad parcial).
- La calculadora no cubre casos particulares: salarios variables, suspensiones, prescripción de vacaciones ni criterios jurisprudenciales.
- El corpus no incluye salario mínimo, IGSS, ISR, reglamentos ni pactos colectivos.
- Los umbrales de abstención se calibraron con un banco pequeño (31 casos) y pueden no generalizar.
- Los documentos internos son sintéticos; en una empresa real habría que integrar autenticación y gestión documental.

## 11. Trabajo futuro

- Reranking con un cross-encoder multilingüe sobre el top 20.
- Clasificador de inyección entrenado en lugar de patrones.
- Actualización automática del corpus al publicarse reformas, con detección de cambios por hash.
- Ampliar el corpus (salario mínimo, IGSS, reglamentos) y el banco de pruebas a más de 100 casos.
- Evaluación con usuarios reales de RR.HH. y medición del tiempo ahorrado.

## 12. Conclusiones

**[PENDIENTE: redactar con los resultados.]** Puntos a cubrir: si se confirmó la hipótesis (híbrido frente a BM25), el valor de separar recuperación (qué dice la ley) y cálculo (cuánto corresponde), la efectividad de la abstención y los guardrails, y las lecciones aprendidas.

## 13. Bibliografía

- Congreso de la República de Guatemala. *Código de Trabajo, Decreto 1441* y sus reformas.
- Congreso de la República de Guatemala. *Decreto 42-92, Ley de Bonificación Anual para Trabajadores del Sector Privado y Público.*
- Congreso de la República de Guatemala. *Decreto 76-78, Ley Reguladora de la Prestación del Aguinaldo para los Trabajadores del Sector Privado.*
- Lewis, P. et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *NeurIPS.*
- Robertson, S. y Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. *Foundations and Trends in Information Retrieval.*
- Reimers, N. y Gurevych, I. (2019). Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks. *EMNLP.*
- Reimers, N. y Gurevych, I. (2020). Making Monolingual Sentence Embeddings Multilingual using Knowledge Distillation. *EMNLP.*
- Cormack, G., Clarke, C. y Büttcher, S. (2009). Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. *SIGIR.*
- Greshake, K. et al. (2023). Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection. *AISec.*
- Es, S. et al. (2024). RAGAS: Automated Evaluation of Retrieval Augmented Generation. *EACL (demos).*
- OWASP Foundation. *OWASP Top 10 for Large Language Model Applications.*
- Documentación de Pydantic, sentence-transformers, rank_bm25, pypdf y Streamlit.
