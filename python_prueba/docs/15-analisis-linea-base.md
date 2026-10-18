# 15. Análisis del registro: cadencia, desfases y decisiones temporales

Fecha: 17 de octubre de 2026. **Análisis descriptivo reproducible de una sesión proporcionada por el autor.** Incluye decisiones para el diseño Python y candidatos temporales de piloto; no acredita calibración física, precisión de detección ni rendimiento integrado.

## 1. Procedencia y alcance

| Elemento | Evidencia |
|---|---|
| Original conservado | [2026-10-17-baseline-recibido.txt](data/2026-10-17-baseline-recibido.txt), texto compartido en la conversación, sin reparar la cola. No es un archivo de captura del broker con metadatos de recepción. |
| SHA-256 del texto UTF-8 | `2b47eda963f45490bedda4590f637f8cd6a700a47e6e0ee2f313c7eb920a3ce7` |
| Tamaño | 192716 bytes. |
| Observaciones utilizables | 490 mensajes JSON completos; mismo esquema `rustio.iot.telemetry.v1` y dispositivo `rpi5-01`. |
| Exclusión | Línea 491: JSON cortado dentro de una clave y seguido de texto del autor. No se infieren valores ni se cuenta como observación. |
| Primer timestamp válido | `2026-10-17T22:08:47.164056+00:00` |
| Último timestamp válido | `2026-10-17T22:25:12.102559+00:00` |
| Duración entre extremos | 984.938503 s: 16 min 24.938503 s. En Lima, 17:08:47–17:25:12 del mismo día. |

No se concatenan los anteriores fragmentos de tres mensajes: no hay evidencia de continuidad entre esos fragmentos y este registro. Los números siguientes usan exclusivamente las 490 líneas completas. La validación de estructura y tipos no demuestra que los sensores estuvieran estabilizados o calibrados.

El registro no aporta recepción del backend, tiempos individuales de adquisición, secuencia/arranque del productor, flags de calidad ENS160, anotación humana ni capturas visuales pareadas. Por ello permite describir publicaciones, pero no medir latencia MQTT, desfase entre dispositivos o retardo radar–cámara. «Línea base» identifica este material de desarrollo; no implica condiciones normales verificadas.

## 2. Reproducción y archivos derivados

Desde la raíz del repositorio, con Python 3 y sin dependencias adicionales:

```bash
python3 python_prueba/docs/analysis/analyze_baseline.py \
  python_prueba/docs/data/2026-10-17-baseline-recibido.txt \
  python_prueba/docs/analysis/2026-10-17-baseline --allow-truncated-tail

python3 -m unittest discover -s python_prueba/docs/analysis -p 'test_*.py' -v
```

Sin `--allow-truncated-tail`, el original falla explícitamente por la línea incompleta. Con esa opción solo se permite excluir una última línea no parseable; un error intermedio, contrato inválido, clave duplicada, número no finito, timestamp sin zona o tiempo no creciente detiene el análisis. El script no ordena, interpola, rellena ni desplaza muestras.

| Archivo | Contenido |
|---|---|
| [analyze_baseline.py](analysis/analyze_baseline.py) | Procedimiento completo, validación y cálculos. |
| [test_analyze_baseline.py](analysis/test_analyze_baseline.py) | Prueba del registro y de entradas inválidas, cuantiles y conservación de duraciones. |
| [summary.json](analysis/2026-10-17-baseline/summary.json) | Hash, exclusión, método, estadísticos y recuentos con precisión numérica. |
| [intervals.csv](analysis/2026-10-17-baseline/intervals.csv) | 489 intervalos, timestamp y líneas de procedencia. |
| [state_transitions.csv](analysis/2026-10-17-baseline/state_transitions.csv) | 42 cambios de modo y si alteran presencia binaria. |
| [presence_segments.csv](analysis/2026-10-17-baseline/presence_segments.csv) | Cinco segmentos de presencia/ausencia declarada, extremos y censura. |

Cuantiles: interpolación lineal en posición `(n−1)·p` sobre valores ordenados. Desviación estándar poblacional, descriptiva de este registro. Las tablas redondean; JSON conserva la precisión calculada. Las 490 muestras temporales no se consideran 490 réplicas experimentales independientes.

## 3. Cadencia observada

Se calculó `Δt_i = timestamp_i − timestamp_(i−1)` para los 489 pares consecutivos.

| Estadístico | Intervalo (s) |
|---|---:|
| Mínimo | 2.014014 |
| Mediana | 2.014112 |
| Media | 2.014189168 |
| p95 | 2.0141912 |
| p99 | 2.01771112 |
| Máximo | 2.020576 |
| Desviación estándar poblacional | 0.000530254 |

No hay timestamps duplicados, retrocesos ni intervalos mayores que 1.5 veces la mediana. Este último es un criterio descriptivo de huecos grandes, no prueba de entrega completa: faltan secuencias para demostrar pérdidas o duplicados MQTT. Tampoco caracteriza el jitter bajo carga del detector/SLM.

### Diferencia acumulada respecto de una pauta ideal

Si se impusiera una cuadrícula hipotética de 2 s, su último instante sería `t_0 + 489·2 s`. La diferencia observada es:

```text
(t_489 − t_0) − 489 × 2 = 6.938503 s
media de exceso por intervalo = 0.014189168 s ≈ 14.189 ms
```

Esto justifica **usar tiempos reales, no número de muestras × 2 s**. No identifica un error del reloj, desfase entre relojes, latencia de red ni desfase físico de sensores. Trabajo realizado antes de un `sleep(2)` sería una explicación posible; sin revisar e instrumentar el productor no se puede atribuir la causa.

**Decisión:** no restar 6.938503 s a los payloads, no corregirlos mediante una recta y no alinear radar/cámara por índice de fila. Conservar los tiempos originales y distinguir cualquier transformación posterior con su método y evidencia. Si se exige período fijo al productor, medir su bucle y programar contra plazos monotónicos absolutos, registrando incumplimientos; no modificarlo a partir de esta conjetura.

## 4. Variación ambiental observada

| Magnitud | Mín.–máx. | Mediana | Primero → último | p95 de `|x_i−x_(i−1)|` | Máximo paso absoluto |
|---|---:|---:|---:|---:|---:|
| Temperatura (°C) | 27.02–27.82 | 27.32 | 27.80 → 27.02 | 0.04 | 0.07 |
| Humedad relativa (%) | 60.89–63.90 | 63.015 | 60.99 → 63.64 | 0.116 pp | 0.22 pp |
| TVOC (ppb) | 24–121 | 72 | 65 → 52 | 18 | 36 |
| eCO2 estimado (ppm) | 401–583 | 500.5 | 487 → 462 | 33.6 | 67 |

`pp` significa puntos porcentuales de humedad. p99 de los pasos: 0.04 °C, 0.1612 pp, 22.12 ppb y 43.12 ppm, respectivamente. La desviación global está en el JSON, pero no se usa como «ruido del sensor»: la temperatura termina 0.78 °C por debajo del inicio y la humedad 2.65 pp por encima. Los extremos tampoco describen toda la trayectoria. No se ha demostrado estacionariedad, independencia ni distribución gaussiana.

AQI vale 1 en 160 mensajes y 2 en 330, con **69 cambios de categoría**. Un disparador por cada cambio de AQI evaluaría 69 transiciones en este registro; no prueba que fueran falsas alarmas, porque no hay etiquetas de eventos. TVOC/eCO2 pertenecen al mismo ENS160 y no son dos corroboraciones independientes. eCO2 sigue siendo estimación, no medición directa de CO2 [S17 de 09](09-fuentes.md#s17-ens160).

**Decisiones:** no activar cámara/SLM por cualquier diferencia, no fijar límites ambientales de seguridad con estos rangos y no escoger un umbral definitivo justo por encima del máximo observado. Comparar ventanas robustas, aplicar persistencia e histéresis y validar con episodios etiquetados. Los pasos medidos son una referencia de escala para el piloto; no son sensibilidad ni error instrumental.

## 5. Radar: modo, presencia y distancias

| Código | Etiqueta exacta del productor | Mensajes | Presencia declarada |
|---|---|---:|---|
| 0 | `Sin presencia` | 50 | Ausente |
| 1 | `Persona en movimiento` | 1 | Presente |
| 2 | `Persona estática` | 413 | Presente |
| 3 | `Movimiento y presencia estática` | 26 | Presente |

Se confirma el mapeo observado `present = state_code in {1,2,3}`; código desconocido significa desconocido, no ausente. Esta es la declaración del radar en su cobertura, no verdad de terreno sobre el aula.

Hay **42 cambios de modo**: 18 de 2→3, 18 de 3→2, uno de 2→1, uno de 1→2, dos de 2→0 y dos de 0→2. Solo **4** cambian presencia binaria y solo **2** son ausencia→presencia. El estado inicial es presencia ya observada: no se inventa una entrada previa. Para B, una regla de entrada sin debounce identificaría esas dos transiciones; no equivale a dos llamadas reales medidas ni garantiza dos entradas físicas correctas.

### Dos segmentos de ausencia declarada

| Líneas | Muestras | Primer–último mensaje UTC | Separación entre extremos | Hasta siguiente presencia* |
|---|---:|---|---:|---:|
| 223–260 | 38 | 22:16:14.323244–22:17:28.845033 | 74.521789 s | 76.535841 s |
| 371–382 | 12 | 22:21:12.416163–22:21:34.571264 | 22.155101 s | 24.169218 s |

\* Duración bajo supuesto de mantener la última etiqueta hasta la publicación siguiente. No mide cuándo salió físicamente la persona. El último segmento de presencia está censurado por el fin del registro. Tampoco se conoce cuánto duraba la presencia inicial antes de empezar a registrar.

Las distancias de movimiento y estática cambian 134 y 268 veces; la total, 339. Sus rangos son 30–455, 30–457 y 0–254 cm. Hay **19 mensajes con distancia total cero y presencia**, y **8 con estado 2 y energía de movimiento positiva**. Una distancia puede permanecer repetida aun con un canal inactivo. Por ello no se deduce ausencia, congelamiento ni movimiento real solo con distancias o energía.

El rango 0–254 de `total_distance_cm`, frente a otros canales que superan 255, merece revisar la decodificación del productor: longitud, orden de bytes, offsets y relación entre campos dentro de la misma trama. **Es una comprobación pendiente, no un fallo de bytes demostrado.** Los datos JSON por sí solos no permiten corregirlo ni imponer que distancia total coincida con otro canal. Conservar los campos originales; usar el código de estado para la presencia declarada hasta verificar el contrato. No desplazar columnas o tiempos para hacerlos coincidir.

## 6. Tratamiento de desfases en el diseño

El contrato [03](03-mqtt-y-contexto.md) se concreta con estas reglas. Son especificación para implementar; el analizador offline no modifica el productor ni implementa la FSM.

### 6.1 Separar cuatro tiempos

1. **Adquisición:** instante/intervalo de lectura de cada sensor y de exposición de cámara. Si no existe, dejarlo desconocido; el timestamp global no lo reemplaza automáticamente.
2. **Publicación y recepción:** conservar `source_timestamp`, recepción UTC y recepción monotónica con ID de arranque. Registrar retención, QoS y secuencia si están disponibles.
3. **Procesamiento:** inicio/fin de cola, adquisición, detector y SLM, con reloj monotónico local para duraciones.
4. **Decisión y reporte:** instante de creación del snapshot y de emisión; recalcular antigüedad al reportar sin alterar el snapshot usado por el modelo.

No restar tiempos monotónicos de máquinas/arranques distintos. Para cámara, conservar metadatos y verificar su dominio de reloj antes de convertir `SensorTimestamp` a UTC [S07 de 09](09-fuentes.md#s07-cámara-y-tiempos). Registrar la correspondencia de relojes y su incertidumbre, incluyendo saltos por sincronización.

Si el tiempo de fuente fuera el de publicación, `recepción_UTC − publicación_UTC` mezclaría transporte con diferencia de relojes. Si marca armado o lectura, añade además otras demoras. Sin semántica y reloj verificados, registrar esa resta como diferencia aparente, no «latencia MQTT»; nunca forzar valores negativos a cero.

### 6.2 Emparejar evidencia por tiempo de adquisición

- Para una captura visual, seleccionar evidencia radar previa y vigente para ese instante, con región comparable. No seleccionar «el último radar» al terminar YOLO o Gemma.
- En línea no utilizar publicaciones futuras. Un replay tampoco puede revelar resultados antes de cuando habrían estado disponibles; ver [07](07-evaluacion.md).
- Si se conocen tiempos centrales `t_r`, `t_v` e incertidumbres acotadas `u_r`, `u_v`, exigir conservadoramente `|t_r−t_v| + u_r + u_v <= crossmodal_max_skew_s`, además de calidad y vigencia. El límite se fija por tarea.
- Con solo recepción y semántica desconocida, conservar emparejamiento aproximado y declarar temporalidad física no verificada. No presentar un desacuerdo como conflicto contemporáneo confirmado.

No se puede fijar aquí un desfase radar–visión «correcto» de 0, 2 o 30 s. Tampoco estimarlo por correlación entre TVOC, eCO2 y presencia: representan fenómenos distintos, carecen de estímulo temporal de referencia y pueden tener respuesta física distinta.

### 6.3 Separar silencio, antigüedad y bloqueo de cómputo

- Un watchdog mide tiempo desde recepción válida en el reloj monotónico local. Ausencia de paquetes no significa ausencia de personas.
- El TTL de una medición depende de adquisición y tarea; recibir una republicación, un retenido o un número repetido no prueba una lectura nueva. Sin tiempos por sensor no puede detectarse toda reutilización de datos antiguos.
- Mantener ingesta y registro disponibles durante visión/SLM. Guardar el snapshot inmutable con hash C–D; evidencias nuevas pueden motivar una nueva versión/seguimiento, sin cambiar retroactivamente lo interpretado.
- Si el resultado llega tarde, conserva valor histórico a su tiempo de captura. Si ya no cumple la vigencia de la pregunta, reportar la limitación o programar seguimiento acotado. Terminar una inferencia no rejuvenece la evidencia.

## 7. Candidatos temporales para el piloto

Estos valores concretan pruebas de desarrollo; **no son un perfil final calibrado ni autorizan una sesión final**. Se mantendrán compartidos entre variantes donde corresponda. Las duraciones se evalúan con timestamps, nunca contando muestras como segundos exactos.

| Parámetro | Candidato | Justificación y coste a comprobar |
|---|---|---|
| Cadencia de referencia del sobre MQTT | 2.014112 s | Mediana observada; dato descriptivo para dimensionar, no obligación del productor ni período por sensor. |
| Watchdog de silencio del sobre: `telemetry_silence_s` | 7 s | Tres intervalos máximos observados suman 6.061728 s; quedan 0.938272 s de margen elegido. Detecta silencio de telemetría conjunta, no calidad ni congelamiento interno del sensor. Debe probarse con carga, retención y fallos. |
| `presence_debounce_s` | 2 s | Exigir dos o más observaciones concordantes que abarquen al menos 2 s. Con esta cadencia, dos lecturas suelen bastar; añade aproximadamente un período desde la primera indicación. Comprobar entradas breves/omisiones. |
| `recent_window_s` ambiental | 30 s | Aproximadamente 15 observaciones; mediana para amortiguar saltos aislados. Es elección de diseño, no tiempo de respuesta medido del sensor. |
| `baseline_window_s` ambiental | 120 s anteriores a la ventana reciente | Aproximadamente 60 observaciones, ventanas sin solapamiento. Evita usar las mismas muestras en ambos lados. Arranque con comparación suspendida hasta tener historia suficiente de 150 s. |
| `min_valid_samples` | 12 recientes y 48 de referencia | Aproximadamente 80% de la capacidad nominal elegida. Cantidad suficiente no reemplaza la distribución temporal: un hueco no se rellena ni confirma persistencia. |
| `persistence_s` ambiental | 10 s | Unas seis evaluaciones consecutivas separadas por esta cadencia para abarcar al menos 10 s. Requiere evidencia nueva y cobertura; el silencio reinicia confirmación. Añade demora que se debe medir. |

Para comparar ventanas en instante `t`: reciente `(t−30,t]` y referencia `(t−150,t−30]`. Congelar referencia al abrir un episodio y usar una banda de recuperación inferior al umbral de apertura. No mantener un promedio que absorba inmediatamente el cambio y declare recuperación artificial.

**Perfil ambiental inicial elegido después de solicitar el autor números concretos:** apertura con cambio absoluto de 0.5 °C, 3 pp de humedad, 50 ppb TVOC o 100 ppm eCO2 entre las medianas de referencia y reciente, sostenido 10 s. Retorno dentro de 0.25 °C, 1.5 pp, 25 ppb o 50 ppm de la referencia conservada, respectivamente, durante 20 s. Se contemplan subidas y bajadas; no son límites absolutos de seguridad. La especificación única y la procedencia de esta elección de ingeniería están en [14, perfil ambiental inicial](14-umbrales-y-activacion.md#perfil-ambiental-inicial-confirmado-para-el-piloto).

**Siguen pendientes** TTL por tarea, `crossmodal_max_skew_s`, cooldown y plazos de visión/SLM. Apertura y recuperación tienen ahora valores iniciales `pilot_candidate`, no calibración: una sola sesión sin etiquetas no identifica qué variación debe detectarse. No se aplicó el filtro completo al registro ni se atribuye una reducción de falsas alarmas a estos candidatos. El piloto debe comprobar también las omisiones de cambios pequeños o lentos que estos umbrales pueden introducir.

El watchdog de 7 s es un parámetro distinto de `source_ttl_s`: no convierte automáticamente en vigente una foto de 6 s ni en inválida una temperatura de 8 s para todas las preguntas. Una fuente puede fallar mientras el resto sigue publicándose.

## 8. Verificación para convertir candidatos en decisiones finales

1. **Productor y relojes:** registrar semántica de timestamp, tiempos por lectura, secuencia/arranque, flags de calidad y configuración MQTT. Para distancias, comparar tramas originales con decodificación; no ajustar números por apariencia.
2. **Cadencia bajo carga:** repetir captura con recepción UTC/monotónica mientras corren detector y SLM. Medir intervalos, colas y disponibilidad del consumidor; probar silencios, reconexión, retenidos y publicación con lectura reutilizada.
3. **Referencia temporal:** anotar cambios de escena con reloj trazable al de captura, conservar resolución/incertidumbre y registrar exposición. Estimar error de alineación y retardo físico por modalidad por separado del transporte/procesamiento. No inducir exposiciones ambientales peligrosas para calibrar.
4. **Eventos etiquetados:** entradas, salidas, movimientos, oclusión y cambios ambientales controlados pertinentes al estudio. Evaluar omisiones y demora con y sin debounce/ventanas, incluyendo eventos más cortos que la persistencia. Una variación numérica no es por sí misma evento relevante ni falso positivo.
5. **Congelamiento:** escoger del piloto por un criterio predefinido que considere omisiones, latencia y llamadas; registrar valores, unidades, procedencia y versión/hash en [14](14-umbrales-y-activacion.md). Mantener esta traza en desarrollo; usar otros registros para evaluación final.

## 9. Texto aprovechable para la tesis

> Se realizó una caracterización descriptiva de 490 mensajes completos de telemetría del dispositivo rpi5-01, recibidos como registro textual del autor. El intervalo entre timestamps consecutivos del productor presentó una mediana de 2.014112 s y un máximo de 2.020576 s. Durante 489 intervalos, la duración acumulada excedió en 6.938503 s la de una pauta hipotética de 2 s. Se decidió evaluar ventanas y antigüedad mediante tiempos registrados, conservando por separado adquisición, recepción y procesamiento, en lugar de derivar duración del número de muestras. Esta diferencia no se interpretó como latencia de transporte ni como desfase entre relojes, al no disponerse de tiempos de recepción ni de una referencia temporal independiente.
>
> El radar presentó 42 transiciones de modo, de las cuales cuatro alteraron la presencia binaria declarada. Por ello se distinguió presencia de modo de detección y se evitó usar las variaciones de distancia o energía como entradas/salidas de personas. La temperatura y humedad mostraron diferencias entre extremos de −0.78 °C y +2.65 puntos porcentuales; la variabilidad global no se adoptó como estimación de ruido estacionario. Se propusieron persistencia, ventanas y supervisión de silencio para el piloto, sin atribuirles calibración, precisión o ahorro aún no medidos. La evaluación final requiere eventos anotados, tiempos de adquisición verificables y registros independientes del desarrollo.

Este texto documenta resultados de la traza y decisiones de diseño; no debe redactarse como si ya se hubieran implementado y validado en la Pi las reglas temporales propuestas.
