# 10. Controles experimentales, registros temporales y CSV

Este documento incorpora las instrucciones posteriores del autor: observar visualmente las decisiones desde una página, introducir fallos por API, registrar recursos en el tiempo, introducir W manualmente y exportar datos experimentales. Es diseño pendiente de implementación.

## 1. Lo que mostrará la página

Una sesión tiene una cronología SSE con el estado actual de la FSM, evidencia utilizada, decisiones y motivos, herramienta activa, resultado parcial, estado de cada fuente y tiempos. Los eventos deben permitir mostrar «no activé cámara porque el radar basta» además de «activé YOLO porque falta conteo».

La pantalla incluye:

- Inicio/final de sesión, variante A–D, escenario, reloj del servidor y estado de cola.
- Diagrama FSM iluminando transiciones confirmadas, sin mostrar pensamiento interno del modelo.
- Sensores con última lectura, antigüedad, alcance, disponibilidad real conocida y disponibilidad efectiva de prueba.
- Controles para fallo/restauración, con confirmación pendiente/aplicada del backend.
- Gráficas de CPU, RAM, temperatura de la Pi y puntos de potencia W introducidos manualmente.
- Formulario de W o contador acumulado, con instante de observación distinto del de guardado.
- Descargas CSV y un ZIP que conserva todos los datos relacionados y su diccionario.

La referencia humana puede introducirse con permisos separados y no aparece en el contexto del SLM. El frontend no decide las transiciones de la política ni cambia los límites del modelo.

## 2. Fallos: alcance y semántica

La capa de prueba se aplica entre cada adaptador y el contexto operacional. Puede seguir recibiendo MQTT en bruto mientras oculta una fuente específica. No detiene el broker, corta alimentación, deshabilita I²C ni modifica GPIO. Eso permite simular fallos en cualquier momento sin cambiar el sistema de adquisición existente.

| Modo | Lo que ve la política de SENSE | Datos anteriores | Qué representa |
|---|---|---|---|
| `disabled` | Fuente indisponible de inmediato y nuevas lecturas bloqueadas | Se conservan como históricos, no respaldan disponibilidad actual | Interruptor «desactivado» solicitado por el autor. |
| `drop` | No llegan nuevas muestras, sin aviso de avería a la política | Último dato puede seguir vigente hasta TTL | Falla silenciosa de adquisición/transporte. |
| `freeze` | Solo permanece la última observación efectiva, con su tiempo original | Envejece; no se rejuvenece al recibir más payloads | Dato congelado/vencido. |
| `error` | La siguiente acción de la fuente devuelve un error tipado | No se sustituye por cero | Captura o herramienta que falla al solicitarse. |

`drop` y `freeze` pueden tener el mismo efecto operacional en una fuente de última lectura; se distinguen por la intervención y registros, sin fingir dos mecanismos distintos si el adaptador no los diferencia. Para contradicciones sintéticas usar un fixture predefinido y marcado, no un editor libre de valores en producción.

La política recibe disponibilidad/error genéricos o ausencia de muestras según el modo. Los detalles de que es un fallo inyectado, el guion futuro y la referencia correcta quedan en el registro experimental, no en el prompt. El panel del investigador sí puede verlos.

### API de fallos

```http
POST /v1/runs/{run_id}/faults
```

```json
{
  "source_id": "ld2410c",
  "mode": "disabled",
  "start_after_s": 0,
  "duration_s": 45,
  "reason": "Prueba de recuperación del radar"
}
```

`start_after_s` es retraso desde la aceptación del comando por el backend. En un plan congelado de sesión, cada fallo usa `start_elapsed_s` relativo al inicio de la sesión; no mezclar ambas referencias temporales. Duración nula se permite en exploración hasta restauración explícita; en ensayos finales usar duración acotada y guion registrado.

Respuesta: `fault_id`, estado `scheduled` o `applied`, tiempos solicitados y efectivos, versión de disponibilidad y secuencia de evento. La respuesta de aceptación no reemplaza el evento `fault.applied` si la aplicación es posterior.

```http
POST /v1/runs/{run_id}/faults/{fault_id}/clear
GET /v1/runs/{run_id}/sources
```

Restaurar es idempotente. Solo puede existir un fallo activo/programado solapado por fuente en este prototipo; una petición incompatible devuelve 409, sin inventar precedencias. IDs de fuente y modos son listas cerradas. No aceptar nombres de topic o comandos arbitrarios.

### Garantías al aplicar y retirar fallos

1. El comando se valida, persiste y aplica mediante el mismo orden lógico que actualiza el contexto.
2. Desactivar ENS160 no afecta SHT40 ni radar aunque compartan un mensaje MQTT.
3. `disabled` invalida inmediatamente su uso actual; `drop` deja que la política detecte envejecimiento según TTL. Esto permite medir tanto reacción a aviso como detección silenciosa.
4. Una acción en curso lleva la versión de disponibilidad con que empezó. Si termina tras una desactivación, su resultado se registra como tardío/suprimido y no se incorpora como evidencia activa.
5. Restauración cambia a `awaiting_fresh_data`; no a `healthy` por el click. Se requiere una muestra nueva fiable o captura exitosa posterior a la restauración. Un payload retenido viejo no basta.
6. Una sesión nueva empieza sin fallos heredados. Al finalizar/cancelar se retiran sus overrides y timers. Si la fuente física sigue rota, seguirá reportándose rota.
7. Una pérdida de conexión de la UI no retira ni prolonga un fallo programado; el backend controla el plazo.

En la Pi hay una sola sesión experimental activa. Esto evita que dos overlays sobre el mismo hardware alteren una comparación sin quedar registrados. Un fallo simulado mantiene productores y posiblemente cámara/modelos residentes; no representa consumo eléctrico de desconexión física.

## 3. Fallos interactivos frente a ensayos comparables

En exploración se puede pulsar un interruptor cuando se desee y observar reacción. En la prueba final, guardar un `fault_plan_id` con tiempos, fuente y duración y aplicarlo por igual a A–D. Un cambio manual no planificado no se oculta: marca `protocol_deviation=true` y se analiza con la regla de inclusión definida antes del experimento.

Las anotaciones de cambios físicos y humanos son distintas de las intervenciones del software. «Hay una persona» no puede usarse como entrada de la política porque el investigador lo escribió en el panel de referencia.

## 4. Muestreo automático de recursos

Frecuencia inicial propuesta: **cada 1 s**, tanto en WAIT como durante inferencia. Medir inicio/final y duración real entre muestras, no asumir un temporizador perfecto. Calentar/descartar la primera estimación incremental de CPU, que carece de intervalo previo [S23].

Registrar:

- Sistema: CPU total y por núcleo, RAM disponible/usada, swap y sus cambios, temperatura CPU, frecuencia y throttling/undervoltage cuando estén expuestos.
- Procesos: API, worker de cámara/YOLO, LiteRT-LM y broker; PID y creación para detectar reinicios, CPU, RSS, y USS/PSS opcionales si están disponibles.
- Operación: variante, episodio/acción activa, largo de cola y muestras faltantes.

La CPU de sistema se expresa 0–100% del equipo; CPU de proceso puede exceder 100% al usar varios núcleos. Guardar ambas con nombres distintos; si se presenta porcentaje del equipo para un proceso, dividir por núcleos efectivos y documentarlo. No sumar RSS como si fuera memoria única. Datos no soportados son vacíos/`null`, no cero.

El pico obtenido a 1 Hz es un **máximo muestreado**. Puede perder picos de memoria o carga más breves; una métrica nativa de high-water mark debe etiquetarse aparte. La frecuencia de la instrumentación se valida en piloto y se mantiene idéntica entre variantes. No hacer una consulta bloqueante de un segundo por cada proceso ni esperar al frontend para tomar muestras.

Persistir primero; SSE entrega copias para los gráficos. Si hay retraso de muestreo o falla de disco, registrar la incidencia y la cobertura temporal. Un CSV descargado al final procede del registro, no de puntos que el navegador consiguió dibujar.

## 5. W manuales y contador acumulado

La API acepta la lectura que el investigador observa en el vatímetro:

```http
POST /v1/runs/{run_id}/power-readings
```

```json
{
  "quantity": "power",
  "value": 7.4,
  "unit": "W",
  "observed_elapsed_s": 120.0,
  "time_uncertainty_s": 3.0,
  "instrument_id": "pmb05-01",
  "observer_id": "operator-01",
  "note": "Lectura de pantalla"
}
```

El backend guarda `recorded_at` y `recorded_elapsed_s` por separado. `observed_elapsed_s` se refiere al reloj de sesión que muestra la página; una lectura transcrita después puede indicar el tiempo anterior. Si no se conoce, se usa recepción como aproximación con `time_basis=entry_time_proxy`, nunca como timestamp físico exacto.

Validar valor finito no negativo, unidades según cantidad y tiempo dentro de la sesión. Para un contador usar `quantity=energy_counter` con `Wh` o `kWh`; conservar valor original y valor normalizado, sin mezclarlo con W. Registrar resolución y exactitud declarada del instrumento en el manifiesto, si están disponibles.

Corregir una transcripción crea otra lectura con `supersedes_reading_id` y motivo; no borra el original. La exportación conserva ambas y señala cuál está activa. La cuenta de energía se recalcula con una revisión identificable. Una lectura tardía después del cierre es admisible como anotación, pero no altera el estado de ejecución ni se atribuye a una acción ocurrida después.

### Integración y gráficos

Cadencia inicial: W cada 30 s, comienzo y final incluidos. En 20 min son 41 lecturas; si esa carga humana interfiere con anotar la escena, asignar otro observador o fijar 60 s en el piloto. No cambiarla por variante ni aumentar muestras solo donde parece haber ahorro.

Calcular trapecios con tiempos reales. Integrar solo pares activos cuya separación respete el máximo fijado, inicialmente 60 s para período nominal de 30 s. No extrapolar antes de la primera ni después de la última muestra, ni atravesar huecos mayores. Entregar `estimated_Wh`, `covered_duration_s`, `coverage_ratio` y regla utilizada. Cobertura incompleta no produce una cifra de consumo total garantizada.

Mostrar línea interpolada diferenciada de puntos medidos. No asignar energía a una inferencia corta usando interpolación de muestras lejanas. Las lecturas acumuladas del contador, si se toman, generan otro resultado con su resolución; no reemplazan ni validan automáticamente la estimación de W.

## 6. Tablas CSV exigidas

Todas las tablas llevan `schema_version`, IDs de enlace y tiempos UTC/relativos cuando correspondan. `run_id`, `block_id`, `scenario_id` y `variant` permiten unir datos; no repetir campos de la escena si no se conocen. Para procesos se usa también `sample_id` y `process_instance_id`.

| Archivo | Una fila por | Columnas principales |
|---|---|---|
| `runs.csv` | Ejecución | espacio, bloque, día, variante, plan, perfiles, inicio/final, estado, desviación y cobertura. |
| `resource_samples.csv` | Muestra de sistema | UTC, elapsed, intervalo real, CPU equipo, núcleos, RAM, swap, temperatura, frecuencia, flags y cola. |
| `process_samples.csv` | Proceso y muestra | sample ID, rol, PID/creación, CPU proceso, RSS, USS/PSS si disponibles y estado de lectura. |
| `observations.csv` | Magnitud observada | fuente, valor, unidad, tiempo fuente/recepción, región, flags, aceptada/suprimida y fallo asociado. |
| `decisions.csv` | Decisión de FSM | episodio, snapshot, origen/destino, razón, acción elegida u omitida y presupuesto. |
| `actions.csv` | Ejecución de herramienta/modelo | herramienta, cola, inicio/final, primer contenido, resultado, error, mosaicos, tokens y artefacto. |
| `faults.csv` | Intervención | fuente/modo, tiempos solicitados/efectivos, restauración, responsable y plan. |
| `power_readings.csv` | Lectura original/corrección | cantidad, valor/unidad original, normalizado, tiempo observado/registrado, incertidumbre e instrumento. |
| `annotations.csv` | Etiqueta humana | escenario, región, tiempo, presencia/conteo, evaluabilidad, observador y adjudicación. |
| `answers.csv` | Respuesta de episodio | pregunta, snapshot, intérprete, estado validado, contenido, referencias, tiempos, followup_status, next_check_at y followup_of_episode_id. |
| `evaluations.csv` | Calificación de respuesta/evento | referencia, evaluador, rúbrica, acierto, abstención, respaldo y revisión. |
| `metrics.csv` | Métrica y alcance | nombre, valor, unidad, denominador, espacio/escenario, método y versión de cálculo. |

`events.jsonl` conserva el evento completo y `manifest.json` las configuraciones/versiones. Arrays, cajas y evidencia anidada se mantienen en JSON/artefactos referenciados; si aparecen en CSV se serializan como JSON válido, sin aplanamiento ambiguo. No se incluyen imágenes ni secretos dentro de las tablas.

Exportar algunas tablas vacías con sus cabeceras es válido: no todas las variantes ejecutan SLM ni todos los ensayos incluyen contador. No crear filas ficticias para que una gráfica tenga datos.

## 7. Consistencia y uso del CSV

`GET /v1/runs/{id}/exports/{table}.csv` acepta solo nombres de tabla de una lista. `GET /v1/runs/{id}/export.zip` incluye CSV, manifiesto, esquema y eventos. Ambos requieren acceso al run; `annotations` y `evaluations` tienen permisos separados si hay evaluación ciega.

Cada exportación toma un corte consistente de datos con `export_id`, hora y límite de secuencia; si la sesión sigue activa se marca parcial. Si existen correcciones posteriores de potencia/anotación, una exportación nueva tiene revisión nueva. No mantener una transacción de lectura larga durante toda una sesión; extraer el corte y cerrar transacción antes de transmitir.

Formato: UTF-8, separador coma, decimal punto, cabecera fija, campos con saltos/comas entrecomillados mediante el escritor CSV estándar, valores ausentes vacíos con su estado de calidad. Documentar la zona horaria y si una duración está en segundos o milisegundos.

Para apertura en Excel ofrecer un perfil seguro que neutralice fórmulas en campos de texto no confiables; conservar el original en JSONL. La exportación de análisis mantiene valores numéricos reales, incluidos negativos legítimos, y documenta cualquier transformación. No modificar silenciosamente datos para acomodar una hoja de cálculo.

## 8. Pruebas de aceptación de estas funciones

1. Desactivar solo ENS160 en un payload compartido: radar y SHT40 siguen entrando.
2. Radar `drop`: el dato envejece al tiempo previsto; `disabled`: indisponibilidad inmediata.
3. Desactivar cámara durante captura: el resultado tardío no se vuelve evidencia activa.
4. Restaurar fuente: estado esperando dato hasta una nueva muestra fiable.
5. Finalizar sesión y empezar otra: ningún fallo/timer de la anterior se hereda.
6. Ejecutar 60 s con inferencia: recursos siguen muestreándose y faltantes quedan explícitos.
7. W constantes de 6 W en 0/30/60 s: integración cubierta da 0,1 Wh; una única lectura no da energía.
8. Separación 90 s con límite 60 s: hueco no integrado; corrección de lectura no duplica el área.
9. Exportar CSV/ZIP: IDs enlazan, cortes coinciden, tablas vacías válidas y textos con coma/salto se recuperan.
10. Abrir/cerrar navegador: ni recursos ni fallos programados dependen de su conexión.
