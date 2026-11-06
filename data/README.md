# Datos

`sources.yaml` es el inventario de fuentes autorizadas: origen, permiso, formato, versión, frecuencia de actualización, sensibilidad y roles con acceso.

## Fuentes públicas (descargar manualmente a `data/raw/`)

Los PDF no se suben al repo (ver `.gitignore`), para no redistribuir ediciones de terceros. Cada integrante los descarga:

| Archivo esperado en `data/raw/` | Documento | Dónde obtenerlo |
|---|---|---|
| `codigo_de_trabajo.pdf` | Código de Trabajo, Decreto 1441 | URL en `sources.yaml`, o la edición publicada por el MINTRAB / CENADOJ |
| `decreto_42_92_bono14.pdf` | Ley de Bono 14, Decreto 42-92 | URL en `sources.yaml` |
| `decreto_76_78_aguinaldo.pdf` | Ley de Aguinaldo, Decreto 76-78 | Buscar una copia oficial (Congreso, MINTRAB, Diario de Centro América) y actualizar la URL |

Después de descargarlos, actualicen el campo `version` del Código de Trabajo con la edición o fecha de la última reforma que incluye el PDF.

## Documentos internos ficticios (sí van en el repo)

`politica_interna_v2026.md` (vigente) y `politica_interna_v2024.md` (derogada) son documentos **sintéticos** de una empresa inventada. Sirven para demostrar:
- **Control de acceso:** solo el rol `rrhh` puede recuperarlos.
- **Versionado:** por defecto se usa la versión vigente; la histórica solo se usa si la consulta pide explícitamente una versión anterior.

El marcador `<!-- page N -->` define la página para las citas.
