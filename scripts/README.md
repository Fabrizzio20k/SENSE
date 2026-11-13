# Análisis reproducible de SENSE

Material experimental del repositorio [Fabrizzio20k/SENSE](https://github.com/Fabrizzio20k/SENSE). Todas las rutas de este documento se refieren a este repositorio.

## Preparar el corpus

Descarga el corpus del [depósito de SENSE en Google Drive](https://drive.google.com/drive/folders/1pedwShJWKiap6f1jQOfRwp1lWyXoSPRF?usp=sharing). Dentro de
`DATA-SENSE` están `E1`, `E2` y `E3`: colócalas directamente en `../data/`,
conservando archivos, subcarpetas e imágenes. El análisis espera, por ejemplo,
`../data/E1/A/R1/metadata.json`; no `../data/DATA-SENSE/E1/...`.
El corpus se distribuye fuera de GitHub y `data/` permanece excluida de Git.

Los complementos pequeños requeridos están en la raíz del repositorio:
`SENSE_evaluacion_Gemma.pdf`, `preguntas_aclaracion_campana_SENSE.txt` y
`preguntas_complementarias_SENSE.txt`. Se verifican sus hashes durante el análisis.

## Ejecutar

Desde esta carpeta:

```powershell
uv run --locked main.py
```

También funciona desde la raíz: `uv run --locked --project scripts scripts/main.py`.
Las rutas se resuelven desde el archivo, no desde el directorio de la terminal.
Se usa el entorno existente (Python 3.14, pandas, Matplotlib y Pillow); no se añaden dependencias.
No requiere la app, la base SQLite, Raspberry Pi, servicios externos ni conexión a Internet una vez sincronizado el entorno.

## Entradas y salidas

- `../data/E*/A-F/R*/`: originales de solo lectura; no se renombran ni corrigen.
- `correcciones_potencia.json`: diez rectificaciones de transcripción confirmadas por el estudiante. Se comprueban identificador, carpeta y valor original; no se aplica un filtro automático de valores altos. En `resultados/potencia_lecturas.csv`, `power_w` conserva el original y `analysis_power_w` indica el valor utilizado. El manifiesto conserva el hash de este registro de correcciones.
- `../images/resultados/`: 54 cronologías y figuras generales y del capítulo, cada una en PNG y PDF vectorial. La codificación por fragmentos se distingue de la evaluación completa por respuesta con rúbrica.
- `resultados/INFORME.md`: cifras por ejecución y mapa de evidencia para las RQ.
- `resultados/ejecuciones.csv`: una fila por ejecución, con identidad de metadatos y carpeta conservadas.
- `resultados/resumen_configuraciones.csv` y `contrastes_descriptivos.csv`: n, mediana y dispersión por configuración y diferencias no emparejadas. No constituyen pruebas confirmatorias.
- `resultados/auditoria.csv`, `esquemas.csv`, `metadatos.json`, `fuentes.json`: incidencias, columnas/celdas vacías y procedencia con hashes SHA-256.
- `resultados/tareas.csv`, `ciclo_tareas.csv`, `latencias.csv`, `decisiones_motivos.csv`, `periodos.csv`: actividad, razones, etapas y duraciones. No equiparar decisiones a inferencias.
- `resultados/potencia_lecturas.csv` y `potencia_segmentos.csv`: lecturas admitidas/excluidas e intervalos efectivamente integrados.
- `resultados/pares_conteo.csv`: todas las referencias candidatas, asociación, desfase y motivo de exclusión. Cero pares produce métrica vacía, no error cero.
- `resultados/preguntas.csv`, `estados_contexto.csv`, `huecos_muestreo.csv`, `segundos_ausentes.csv`: cobertura operativa y faltantes.
- `resultados/fallos.csv`: etapas, preexistencia y solapamientos. No aplica tasas de éxito a fallos no evaluables.
- `resultados/figuras.json` y `FIGURAS.md`: catálogo y explicación de cada figura.
- `resultados/manifest.json`: estado final `COMPLETED` o `FAILED`, versiones y hashes de scripts, entradas y derivados. Si hay error, revisar `error.txt` y corregirlo antes de citar los resultados; no considerar terminada una generación con estado `FAILED`.

Los derivados se regeneran en las mismas rutas. Cierra los CSV abiertos en Excel antes de volver a ejecutar. Si se interrumpe la ejecución, puede haber derivados parciales; manda el estado del manifiesto. No ejecutar dos instancias simultáneas.

## Respuestas de IA

Abrir `resultados/revision_ia.html` en un navegador local. Contiene cada salida conservada de Gemma, la imagen enlazada cuando existe, la entrada `SLM_INPUT`, referencias y publicaciones. Los snapshots y los objetos originales se guardan también en `resultados/evidencia_ia/` y `respuestas_ia.json`.

`resultados/fragmentos_ia.csv` recoge los textos de todos los campos de la salida original, incluidos campos extra que el sistema no trasladó a su resumen. Los fragmentos de recomendaciones y desconocidos no deben interpretarse automáticamente como afirmaciones factuales; se revisan según su función y el prompt concreto.

La primera ejecución crea `revision_ia.csv` junto a main.py. **Nunca sobrescribe ese archivo existente.** Permite codificación posterior explícita por fragmento, con estas categorías: `SUSTENTADA`, `PARCIAL`, `CONTRADICHA`, `SIN_SUSTENTO`, `NO_EVALUABLE`. Completar categoría, evidencia, justificación, revisor y fecha ISO con zona horaria; mantener IDs y texto originales. Si no hay referencia suficiente, documentarlo; no usar la predicción como verdad. Para nuevos fragmentos de una campaña ampliada, incorporar sus filas desde `resultados/fragmentos_ia.csv` conservando las revisiones anteriores.

Al ejecutar de nuevo, las revisiones válidas se incorporan en `revision_ia_validada.csv`, `revision_ia_resumen.csv` y `estado_revision_ia.json`; la figura semántica separa Q6/Q7. Las pendientes no se clasifican como correctas ni incorrectas. Este flujo prepara la evaluación semántica y sus denominadores; **no la sustituye por heurísticas ni hace llamadas a otra IA**. Distinguir evidencia original disponible, veracidad independiente y cumplimiento de la tarea. VALIDATED es formal. `respuestas_ia_resumen.csv` resume vínculos, tokens y estado de revisión por tarea.

## Criterios y límites

Las definiciones reproducibles completas se escriben en `resultados/metodos.json`:

- Presencia: representación uniforme `1 = presente`, `0 = ausente`, con estado y antigüedad. Los informes y gráficos no segmentan por etiquetas de origen; los faltantes no se convierten en ausencia.
- Potencia: trapecios solo en intervalos con extremos válidos, misma frontera eléctrica y separación <= dos intervalos nominales (120 s si el nominal es 60). Incluye lecturas repetidas reconfirmadas mediante nueva observación, según aclaración de los observadores del 12-11-2026; no extrapola extremos ni huecos largos. Reporta Wh **cubiertos**, cobertura y W ponderados. El criterio de hueco es exploratorio; no demuestra señal continua ni exactitud instrumental.
- Conteo: incluye referencias repetidas reconfirmadas. El `task_id` vincula el conteo a la escena capturada aunque haya demora de escritura, según el procedimiento confirmado. Solo sin vínculo busca la captura más cercana con desfase máximo del config (3 s si falta). Conserva horas originales, desfases, demora y número de pares dentro de tolerancia; una anotación por captura, priorizando vínculo explícito. Filas sin conteo son registros de otra información. No calcula recall global.
- Recursos: utiliza instantes de recurso únicos con antigüedad <= dos intervalos nominales. Mantiene las escalas de CPU; memoria exportada como MB se presenta como MiB. El pico del proceso puede abarcar más de una ejecución.
- Preguntas: estados entre publicaciones consecutivas cercanas, sin rellenar huecos ni extender la última publicación. RESOLVED significa disponibilidad operativa; no es exactitud. Las publicaciones repetidas no son inferencias nuevas.
- Tareas: campos vacíos permanecen desconocidos. Una tarea completada no simulada puede tener model_executed vacío; se contabiliza con esa salvedad, sin inventar el flag True. Fallos simulados se conservan aparte.
- Comparaciones: tres ejecuciones por celda; se muestran puntos y mediana de las ejecuciones completas, conservando el orden A–F y la variación natural. Los identificadores de software permanecen visibles; los observadores aclararon que los cambios fueron de almacenamiento/interfaz. La rúbrica describe las respuestas disponibles por escenario y tarea, sin convertir Q6/Q7 en un experimento emparejado.

Los HTML y JSON pueden contener texto e imágenes enlazadas de la campaña. Se mantienen locales y se excluyen de Git mediante este directorio; no publicarlos automáticamente. Las figuras comparativas no incluyen fotografías ni identificadores personales.

## Material para el capítulo de resultados

La misma entrada `uv run --locked main.py` ejecuta también `publication.py`: genera seis figuras `cap4_*.pdf/png`, las tablas LaTeX en `../secciones/resultados/` y `resultados/investigacion/cifras_capitulo.json`. El capítulo utiliza además `14_pares_conteo.pdf`. Las tablas numéricas se sobrescriben al regenerar; la redacción de `capitulo5.tex` se mantiene separada y debe revisarse si cambian las fuentes o los criterios.

`evaluacion_gemma.json` transcribe las 149 fichas de `../SENSE_evaluacion_Gemma.pdf`, aportado por el estudiante. Conserva tres puntuaciones (exactitud, pertinencia y sustento), error crítico, cumplimiento de tarea, justificaciones y página de origen. Es una adaptación de Rico y Larson (2026), DOI [10.3390/aisens2020007](https://doi.org/10.3390/aisens2020007): el artículo usa cinco dimensiones y SENSE tres. La procedencia consignada en el PDF es una evaluación posterior asistida por IA, diferenciada de la revisión conjunta de los dos observadores de campaña. No se atribuyen las notas a dos calificadores independientes.

`rubric.py` verifica la integridad del PDF, la cobertura exacta del corpus, las identidades y hashes de respuestas, las notas enteras 1–5 y los promedios. Exporta `resultados/evaluacion_rubrica.csv/json` y `evaluacion_rubrica_resumen.json`, con resúmenes por ejecución, configuración, escenario y pregunta. El visor `revision_ia.html` muestra cada nota junto con la respuesta y permite consultar las justificaciones y la página de origen. No vuelve a juzgar el contenido ni convierte tareas sin respuesta en notas cero. La media es descriptiva, no un porcentaje de exactitud física. La figura `cap4_calidad_gemma` y la tabla `calidad_gemma.tex` proceden de esos mismos juicios.

`casos_ia.json` conserva ocho antecedentes documentales preliminares y su procedencia. El flujo comprueba extractos y evidencia y exporta `CASOS_IA.md` y `casos_ia.csv`, separados de la evaluación completa. Sus identificadores C1–C8 no equivalen a C001–C149 del PDF. La plantilla por fragmentos se preserva sin rellenarla con las notas por respuesta. El archivo `../imagenes pendientes para resultados.md` explica la selección expositiva.

**Estado del 12-11-2026:** análisis de 54 exportaciones y 149 fichas de evaluación. Se obtuvieron 758 pares de conteo (MAE 1,73; RMSE 2,61; 280 exactos), cobertura eléctrica mediana de 88,44 % y calidad media de 3,45/5 en la rúbrica, con 46 errores críticos y 51 respuestas que cumplen la tarea. El capítulo integra siete figuras y cinco tablas de resultados. El manifiesto conserva hashes de fuentes, código, evaluación y derivados; las pruebas de `test_metrics.py` y `test_rubric.py` se ejecutan con `python -m unittest discover -s scripts -p 'test_*.py' -v` desde la raíz.

**Actualización del 13-11-2026:** se aplicaron diez rectificaciones individuales confirmadas mediante `correcciones_potencia.json`, sin cambiar fuentes originales; pasaron 17 pruebas y la comprobación de correspondencias. Las medianas de potencia media ponderada son 3,67 W en D y 4,47 W en E. La discusión incorpora dos referencias sobre inferencia y las conclusiones están activas en el documento principal.

`resultados/investigacion/cifras_capitulo.json` incluye `power_by_mode`: número de ejecuciones, ejecuciones con IA completada, distribución de potencia media ponderada, cobertura y energía cubierta. Las medias incluyen espera y procesamiento selectivo; no representan potencia exclusiva de Gemma. El número de correcciones aplicadas se registra por ejecución y en el resumen general.

La generación prepara además `../secciones/anexos/matriz_ejecuciones.tex` (filas de 54 identidades con carpeta conservada) y `correcciones_potencia.tex` (tabla de diez rectificaciones documentadas). Sus hashes quedan en `annex_table_hashes` del manifiesto. Se incluyen en el documento de anexos; no requieren modificar las fuentes ni publicar el corpus en GitHub.

Las latencias negativas de fallos se conservan en su campo original, se señalan en `auditoria.csv` y se excluyen de los campos numéricos y figuras. No se convierten en cero.

## Comprobaciones del flujo

```powershell
uv run --locked python -m unittest discover -s . -p "test_*.py" -v
```

Verifican ausencia frente a cero, integración con límites/huecos/duplicados, asociaciones de conteo, publicaciones repetidas, simulaciones y preservación de revisiones. Las pruebas no validan físicamente los sensores o las anotaciones.
