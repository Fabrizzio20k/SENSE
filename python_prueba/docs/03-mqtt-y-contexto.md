# 03. MQTT y contratos de evidencia

## 1. Reutilizar la adquisición existente

El autor ya dispone de estas proyecciones del mismo mensaje:

```bash
mosquitto_sub -h 127.0.0.1 -t 'rustio/rpi5-01/telemetry' | jq '.environment.sht40'
mosquitto_sub -h 127.0.0.1 -t 'rustio/rpi5-01/telemetry' | jq '.environment.ens160'
mosquitto_sub -h 127.0.0.1 -t 'rustio/rpi5-01/telemetry' | jq '.presence'
```

El backend necesita **una suscripción al topic completo**, no tres procesos `mosquitto_sub` permanentes. Divide el payload por fuente y conserva su vínculo con el mensaje original. Los comandos sirven para diagnóstico; Paho es una opción para la conexión persistente [S06].

El autor proporcionó primero proyecciones por fuente, después tres mensajes completos y finalmente un registro de 490 mensajes completos el 17 de octubre de 2026. El contrato normal queda observado; aún faltan comportamiento de fallos, semántica precisa del timestamp y transporte. No reconstruir mensajes uniendo proyecciones de momentos distintos; preguntas Q01–Q03. El análisis reproducible del registro posterior está en [15](15-analisis-linea-base.md).

### Sobre real confirmado

| Campo | Valor observado / interpretación |
|---|---|
| `schema` | `rustio.iot.telemetry.v1`; validar versión soportada antes de normalizar. |
| `device_id` | `rpi5-01`; conservar origen junto al topic. |
| `timestamp` | ISO 8601 con offset `+00:00`; tiempo del productor en UTC. Falta confirmar si marca medición, armado o publicación. |
| `environment`, `presence` | Ambos viajan en un mismo mensaje; no prueba que todos los sensores se midieran simultáneamente. |

Timestamps recibidos: `2026-10-17T22:07:12.487237+00:00`, `2026-10-17T22:07:14.501293+00:00` y `2026-10-17T22:07:16.520794+00:00`. Sus intervalos son **2.014056 s** y **2.019501 s**: cadencia observada aproximadamente 2 s, no un período fijo garantizado ni una medida de latencia de transporte.

El registro posterior caracteriza 489 intervalos: mediana **2.014112 s**, p99 **2.01771112 s** y máximo **2.020576 s**. Acumula **6.938503 s** por encima de una pauta hipotética de 2 s; no es un desfase medido entre relojes ni una latencia MQTT. No corregir timestamps por esa cantidad ni calcular duraciones como muestras × 2 s. Ver método y límites en [15, sección 3](15-analisis-linea-base.md#3-cadencia-observada).

Los mensajes completos no incluyen secuencia, boot ID ni flags explícitos de validez/calentamiento. No asumir que los valores ambientales tienen calidad certificada por esa ausencia. Registrar `source_timestamp` en procedencia y `received_at` local por separado; hasta confirmar la semántica, no etiquetar el timestamp global como medición exacta de cada sensor. Tampoco se puede obtener QoS/retención de este JSON ni demostrar sincronización del reloj con solo su formato.

### Campos reales observados

| Path relativo al payload | Muestra/rango observado | Tratamiento interno |
|---|---|---|
| `environment.sht40.temperature_c` | 27.78, 27.76, 27.78 | Temperatura en °C. |
| `environment.sht40.humidity_percent` | 60.89, 60.83, 60.81 | Humedad relativa en %; diferencias en puntos porcentuales. |
| `environment.ens160.aqi` | 1 en las tres muestras iniciales; 1/2 en el registro posterior | Índice del productor; confirmar escala/algoritmo antes de interpretarlo. |
| `environment.ens160.tvoc_ppb` | 47, 42, 44 | Indicador TVOC en ppb según nombre del campo. |
| `environment.ens160.eco2_ppm` | 452, 441, 444 | eCO2 estimado en ppm; no CO2 medido. |
| `presence.state_code` | 0, 1, 2 y 3 en el registro posterior | Código tipado; conservar junto a etiqueta. |
| `presence.state` | `Sin presencia`; `Persona en movimiento`; `Persona estática`; `Movimiento y presencia estática` | Etiquetas de 0/1/2/3 respectivamente; no instrucciones para el modelo. |
| `presence.motion_distance_cm` | 55 y 30 | Distancia del canal de movimiento; no asumir válida sin detección correspondiente. |
| `presence.motion_energy` | 0 y 100 | Valor crudo del radar, no probabilidad ni energía eléctrica. |
| `presence.static_distance_cm` | 55 y 30 | Distancia del canal estático con alcance del radar. |
| `presence.static_energy` | 100 | Valor crudo, no confianza calibrada ni certeza de presencia. |
| `presence.total_distance_cm` | 0 en proyecciones previas; 46/47 en mensajes completos con estado 2 | Conservar como crudo; semántica/cálculo pendientes del productor. |

El registro posterior confirma los cuatro códigos: 0 declara ausencia, 1/2/3 presencia. El paso 2 → 3 → 2 cambia el modo de detección, pero mantiene presencia: no equivale a una entrada/salida ni debe disparar repetidamente una regla B definida como ausencia → presencia. Hay 42 cambios de modo, solo 4 de presencia binaria y 2 de ausencia → presencia. No se confunden estas etiquetas con verdad de terreno. Un código desconocido se marca no soportado, no se convierte en ausencia.

`total_distance_cm=0` no puede interpretarse como ausencia en estas muestras, porque coexiste con detección estática/mixta. Tampoco un cambio 55 → 30 demuestra que una persona se acercó: falta referencia y semántica del canal.

En el registro posterior hay 19 mensajes de distancia total cero con presencia y 8 de código 2 con energía de movimiento positiva. La distancia total está en 0–254 cm mientras otros canales superan 255: revisar tramas y decodificación del productor, sin afirmar un error de bytes ni reparar valores sin prueba. Distancias/energías se conservan crudas y no determinan presencia ni contemporaneidad de modalidades; ver [15, sección 5](15-analisis-linea-base.md#5-radar-modo-presencia-y-distancias).

### Qué permiten decir estas muestras

La amplitud observada en tres lecturas es 0.02 °C, 0.08 puntos de humedad, 5 ppb TVOC y 11 ppm eCO2. Son diferencias descriptivas de un fragmento muy corto, no una estimación de ruido representativa ni umbrales de activación. Los bloques de SHT40, ENS160 y radar se consultaron sucesivamente: no asumir simultaneidad entre ellos.

Las duraciones mostradas por el shell no prueban un período exacto de publicación. Obtener un registro con tiempos de fuente o de recepción. Tampoco la falta de un campo status en la proyección demuestra que no exista en otra parte del payload.

En el lote completo posterior, SHT40 informa 27.66/27.67/27.65 °C y 61.04/61.07/60.99 %; ENS160, TVOC 64/62/62 ppb y eCO2 485/481/481 ppm; AQI permanece 1. Radar permanece en código 2, distancia estática 67 cm y energía estática 100/96/100. Son otro fragmento de observación, no se concatenan con el anterior como una serie continua ni calibran los umbrales.

## 2. Contrato interno propuesto

Una observación normalizada contiene:

| Campo | Propósito |
|---|---|
| `observation_id` | ID estable del registro interno. |
| `source`, `device_id`, `metric` | Sensor y magnitud, por ejemplo SHT40/temperatura. |
| `value`, `unit` | Valor tipado o `null`; unidad explícita. |
| `observed_at` | Tiempo de medición si existe y su reloj es conocido. |
| `received_at` | Recepción UTC del backend; no reemplaza el tiempo de medición. |
| `received_monotonic_ns`, `boot_id` | Medición de intervalos local a ese arranque. |
| `timestamp_basis` | `source`, `receipt_only` o `sensor_metadata`. |
| `scope_id` | Cobertura radar, ROI visual o punto de medición. |
| `quality_flags` | Error, calentamiento, reloj desconocido, oclusión, etc. |
| `provenance` | Topic, ID/secuencia del productor, versión de adaptador y referencia al payload. |

Ejemplo de estructura interna; sus números y nombres de claves no son una captura del hardware:

```json
{
  "observation_id": "obs-001",
  "source": "sht40",
  "device_id": "rpi5-01",
  "metric": "temperature",
  "value": 26.0,
  "unit": "degC",
  "observed_at": null,
  "received_at": "2026-10-17T18:00:00Z",
  "received_monotonic_ns": 1200000000,
  "boot_id": "boot-example",
  "timestamp_basis": "receipt_only",
  "scope_id": "environment-point-1",
  "quality_flags": ["source_timestamp_missing"],
  "provenance": {"topic": "rustio/rpi5-01/telemetry", "producer_sequence": null}
}
```

## 3. Validez, frescura y conflicto son ejes distintos

Una observación puede ser numéricamente válida pero antigua. Un conjunto puede contener dos observaciones válidas y contemporáneas que se contradicen. Por eso se propone:

- **Disponibilidad/calidad:** nunca observado, válido, inválido o fuente fallida.
- **Frescura:** vigente, antigua o desconocida.
- **Consistencia entre observaciones:** sin conflicto, en conflicto o no comparable.

`unknown`, `stale` y `conflicting` del PDF aparecen en la salida contextual, sin obligar a borrar el valor original. El conflicto referencia las observaciones que lo producen y la regla de comparación.

No considerar dos observaciones comparables solo porque ambas hablan de personas. Definir las regiones radar, cámara e intersección; un radar positivo y conteo cero fuera de la intersección pueden ser compatibles. Tampoco exigir acuerdo entre una foto antigua y radar actual.

## 4. Tiempo y snapshots

Definir TTL por variable y tarea durante el piloto. Un mismo TTL global para radar, temperatura y conteo no tiene justificación automática.

Si existe tiempo fiable de fuente, la frescura se deriva de ese tiempo y de la tolerancia de reloj. Si solo hay recepción, registrar una aproximación de frescura y no afirmar sincronización física. No transformar un mensaje retenido recién recibido en medición nueva. La retención MQTT no garantiza vigencia [S05].

Un snapshot debe incluir `snapshot_id`, versión, instante de referencia, observaciones seleccionadas, flags, necesidades pendientes y reglas aplicadas. Para C–D guardar una representación serializada estable y su hash. Evitar reconstruir el snapshot desde «los últimos valores» cuando el intérprete ya empezó.

El resultado de una foto conserva `captured_at` o intervalo de exposición, `processed_at` y `published_at`. Si tardó 30 segundos, ese retraso importa para hablar de presencia actual. Una inferencia antigua puede seguir siendo una descripción histórica válida; no debe etiquetarse como actual por acabar de terminar.

La política temporal concreta y su justificación están en [15, sección 6](15-analisis-linea-base.md#6-tratamiento-de-desfases-en-el-diseño): emparejar por adquisición, separar incertidumbre de reloj y procesamiento, no usar evidencia futura en replay y evaluar vigencia también al reportar. El watchdog candidato de 7 s supervisa silencio del sobre MQTT; no sustituye TTL por sensor/tarea ni prueba adquisición reciente.

## 5. Integridad de la ingesta

Validar JSON, tamaño de payload, tipo, unidad y esquema por productor. Rechazar `NaN`, infinito, booleanos usados como números y strings inesperados. Valores fuera de especificación se conservan como anomalía con motivo, sin convertirse en medición válida.

Tratar cada fuente por separado: un ENS160 en calentamiento no invalida necesariamente la temperatura del SHT40 en el mismo mensaje. Conservar status del dispositivo si existe; no reconstruirlo por el valor de eCO2.

Los mensajes pueden repetirse o llegar después de datos más recientes. El identificador preferido para deduplicar es productor + arranque + secuencia; el ID de paquete MQTT no es un ID global de medición. Si el productor no ofrece IDs, conservar recepción y documentar la deduplicación limitada; no descartar dos mediciones iguales solo por igualdad de contenido. QoS no reemplaza estas reglas [S05].

No retroceder el estado actual al recibir una observación antigua; sí conservarla en historial. Tras reconectar, registrar huecos y retención. Sin publicar durante el TTL, marcar stale aunque el broker siga conectado.

Para los ensayos, insertar una capa de fallos después de descomponer el payload por fuente. Desactivar ENS160 no oculta SHT40 ni radar aunque viajen en el mismo mensaje. Conservar el flujo original separado para diagnóstico y la transformación aplicada; el razonador solo ve la evidencia operacional permitida. Modos y restauración se definen en [10 — controles y CSV](10-controles-y-csv.md).

Con `loop_start`, el callback MQTT corre fuera del event loop de la API. Transferir mensajes por un puente seguro; no modificar directamente una `asyncio.Queue` desde otro hilo. El callback no hace inferencia ni espera SQLite lenta. La política de desbordamiento de ingesta debe registrarse; perder mensajes silenciosamente invalida la evaluación.

## 6. ENS160 y límites de interpretación

El PDF y la ficha del fabricante distinguen eCO2 estimado de CO2 medido. Usar unidades y nombres completos, y revisar bits de validez/calientamiento según el firmware real [S17]. Un cambio puede describirse como variación del indicador; no es prueba de humo, causa ambiental o riesgo certificado.

Los umbrales analíticos sirven para detectar cambios definidos por el estudio, no para diagnosticar seguridad. El radar indica detección en su cobertura, sin conteo fiable de individuos. La referencia humana no calibra físicamente los sensores ambientales.

## 7. Almacenamiento mínimo

Una base SQLite basta para metadatos, observaciones, snapshots, episodios y eventos. Propuesta de tablas lógicas, no migración implementada:

```text
runs(run_id, manifest, config_hash, status, start_time, end_time)
observations(observation_id, source, observed_at, received_at, payload)
snapshots(snapshot_id, run_id, reference_time, content_hash, payload)
episodes(episode_id, run_id, snapshot_id, status, result)
events(run_id, sequence, episode_id, type, wall_time, monotonic_ns, payload)
artifacts(artifact_id, run_id, kind, content_hash, storage_ref, retention)
annotations(annotation_id, session_ref, observer_id, time, scope, label)
```

SQLite WAL permite lectores concurrentes con un escritor; no múltiples escritores simultáneos ni base compartida por NFS [S10]. Mantener transacciones cortas. Las imágenes viven fuera de la base con ID y hash, sujetas a retención; no insertar base64 en cada evento. Los snapshots pueden referenciar observaciones compartidas entre sesiones sin duplicar toda la ingesta.

## 8. Pruebas previstas

Mensajes reales de cada sensor, error parcial, clave faltante, `null`, JSON roto, unidad inesperada, reloj futuro, retención antigua, reconexión, duplicado, secuencia invertida y ausencia prolongada. Cada caso debe tener una salida de normalización esperada y no requerir SLM.

Para histórico, comprobar que «sin cambios de valor» no significa «sin nuevas muestras». Para una tendencia, exigir una ventana mínima y cobertura de muestras; una sola lectura no demuestra aumento.
