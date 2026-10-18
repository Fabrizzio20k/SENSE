# 07. Evaluación y mediciones reproducibles

## 1. Qué debe poder responder el experimento

Conservar las tres preguntas de §3.1 del PDF:

- **H1:** aporte de combinar modalidades frente a cada modalidad individual.
- **H2:** reducción de activaciones con una tasa de omisión aceptable definida antes de la evaluación final.
- **H3:** aporte de la interpretación SLM frente a reglas con exactamente la misma evidencia.

No redefinir H3 como «Gemma responde más bonito» ni H2 como «se llamaron menos modelos». La utilidad depende de tareas resueltas con respaldo y eventos no omitidos.

## 2. Configuraciones principales

| Variante | Política de visión | Intérprete | Qué aísla |
|---|---|---|---|
| A | Periódica, intervalo fijado en piloto | Reglas | Referencia de procesamiento periódico. |
| B | Disparo simple por evento/umbral fijado | Reglas | Alternativa de bajo costo sin contexto adaptativo completo. |
| C | Adaptativa por estado de conocimiento | Reglas | Efecto de la política manteniendo intérprete determinista. |
| D | Misma política que C | SLM solo cuando procede; reglas para respuestas directas | Sistema adaptativo con interpretación generativa. |
| E_visual | Solicitud visual directa, explícitamente separada | Gemma recibe imagen | Extensión respecto al PDF; comparación exploratoria de ruta visual. |

Mantener detector, regiones, hardware, productores MQTT, perfil de cámara y configuración de registro constantes para A–D. Si D cambia guardas o adquiere nuevos datos por sugerencias del SLM, deja de aislar el aporte interpretativo; etiquetar esa variante aparte.

Para el contraste puro C–D, congelar un corpus de preguntas y snapshots idénticos. Guardar hash, evidencia y referencia temporal. Una solicitud de información del SLM se evalúa como salida; no altera ese corpus.

## 3. Dos vías de evaluación

### Replay emparejado

Reproducir la misma secuencia temporal a A–D y a ablaciones de fuentes. El registro debe contener las imágenes que cualquier variante pueda solicitar; un dataset grabado solo cuando C quiso mirar no permite evaluar oportunidades que A o B habrían usado.

Las políticas usan un reloj experimental reproducible para TTL, ventanas y cooldown. La duración de procesamiento puede simularse mediante costos medidos para estudiar decisiones, pero debe rotularse como simulación; no reportarla como latencia de hardware medida. Un replay que hace disponibles inmediatamente resultados futuros produce fuga temporal.

El primer registro analizado de desarrollo está en [15](15-analisis-linea-base.md): 490 mensajes completos, cadencia mediana 2.014112 s. No convertir filas a segundos mediante un período supuesto de 2 s ni usar esta sesión para validar los mismos umbrales que ayude a elegir. No tiene anotación humana, recepción ni adquisiciones individuales; sus 42 cambios de modo y 4 de presencia son etiquetas del productor, no aciertos/falsos positivos medidos. Congelar candidatos en piloto y evaluar en registros independientes.

Ocultar fuentes mide aporte informativo, no ahorro por apagar sensores. Las anotaciones son inaccesibles a la política y al SLM. Separar archivos y permisos de anotación de la entrada operacional.

### Ejecución física

Correr cada configuración en la Pi bajo escenas preparadas y monitoreo. Orden aleatorizado o contrabalanceado por sesión; geometría, luz y tiempos humanos registrados. No presentar escenas físicas distintas como si fueran fotogramas idénticos. Usar varias sesiones y reportar variación entre ellas.

Distinguir carga fría, primera llamada visual y operación estable. La primera imagen puede cargar un encoder bajo demanda; sin instrumentación no atribuir toda esa demora al procesamiento visual recurrente.

## 4. Métricas y denominadores

| Dimensión | Métrica | Denominador / observación |
|---|---|---|
| Presencia | Matriz de confusión, precisión, recall, F1 y macro-F1 cuando corresponda | Ventanas con región y referencia comparable; informar prevalencia. |
| Conteo | MAE y distribución de error | Solo imágenes/ventanas con conteo humano evaluable. |
| Cobertura | Preguntas contestadas con evidencia válida / preguntas evaluables | Por tipo de pregunta y modalidad; no confundir cantidad de respuestas con aciertos. |
| Abstención | Frecuencia y proporción de abstenciones justificadas/injustificadas | Todas las preguntas evaluables; informar también desempeño condicionado a responder. |
| Eventos | Omisiones / eventos de referencia | Emparejamiento temporal y tolerancia congelados. |
| Falsas alarmas | Eventos sin referencia por hora | Tiempo realmente observado; regla de deduplicación fijada. |
| Activaciones | Capturas, imágenes YOLO, mosaicos, encoder visual, SLM por hora/evento | Separar captura física de procesar una imagen ya guardada. |
| Salida SLM | Respuestas completas y sustentadas; afirmaciones sin respaldo | Rúbrica por pregunta y por afirmación, con denominadores publicados. |
| Adquisición | Peticiones innecesarias, necesarias e imposibles | Oracle/criterio de pertinencia definido antes del resultado. |
| Latencia | Mediana, p95, distribución | Cola, acción, respuesta validada y evento físico a salida por separado. |
| Recursos | CPU, RSS/USS cuando sea posible, pico de memoria, swap y throttling | Árbol de procesos completo, no solo API Python. |
| Potencia | W observados manualmente con tiempo | Intervalo, resolución, transcripción y huecos de muestreo. |
| Energía | Contador por ejecución y/o integración estimada de W | Métodos separados, sin equiparar una estimación con lectura directa. |

Cuando un denominador sea cero, reportar no definido, no un cero artificial. No tratar `null`/no evaluable como conteo cero. F1 solo en respuestas emitidas puede ocultar abstenciones; acompañarlo siempre de cobertura y tasa de abstención.

La reducción de activaciones respecto a A es `1 - tasa_X/tasa_A`, para exposiciones comparables y `tasa_A > 0`. Nueve mosaicos sobre una foto cuentan como una captura, un trabajo de conteo y nueve inferencias del detector; no esconderlos dentro de una sola activación genérica.

## 5. Rúbrica de respuestas

La referencia para magnitudes numéricas es evidencia registrada, no conocimiento inventado por el evaluador. Para personas, usar anotaciones independientes. Propuesta de campos de evaluación:

1. Responde la pregunta dentro del alcance espacial/temporal.
2. Valores y cambios numéricos coinciden con evidencia válida.
3. Distingue observación, hipótesis y desconocido.
4. No atribuye causalidad ni peligro sin respaldo.
5. No solicita datos ya disponibles o irrelevantes.
6. Si no puede contestar, la abstención explica la limitación correcta.

Ejemplo negativo real de la conversación: atribuir más precisión/control a la llama y mayor riesgo a la mano. Es un fallo de contenido, aunque la latencia y el formato sean buenos. No usarlo como ensayo final después de ajustar prompts contra él; pertenece al piloto/diagnóstico.

Para afirmaciones sin respaldo, definir una unidad de afirmación y revisar una muestra con dos evaluadores ciegos a la variante. No usar al mismo SLM como único juez de su propia calidad. Reportar desacuerdos y adjudicación. Un schema válido es una métrica de estructura, no prueba de verdad.

## 6. Instrumentación de tiempos

Cada acción conserva `queued`, `started`, `input_ready`, `first_content`, `last_content`, `validated`, `finished` cuando la etapa lo permite. Marcar campos no observables como `null`, sin rellenarlos por diferencia especulativa.

Para el SLM distinguir:

- Tiempo hasta primer contenido: incluye envío, posible carga, prefill y generación inicial.
- Tiempo de emisión entre primer y último bloque: aproximación de streaming, no un medidor exacto de cada token.
- Tokens de salida / tiempo total: throughput extremo a extremo de la petición.
- Tokens/s del runtime: usar métricas nativas si están disponibles; no equipararlas a los cocientes anteriores.

En las observaciones comunicadas por el autor:

| Caso | Total | Primer contenido | Emisión | Tokens |
|---|---:|---:|---:|---:|
| Texto | 17,79 s | 4,08 s | 13,67 s | 81 |
| Imagen | 39,06 s | 29,12 s | 9,95 s | 56 |

No son muestras suficientes para mediana/p95, ni aíslan tiempos de encoder. El script de prueba empleaba `max_tokens`; verificar que el paquete realmente aplica ese campo o cambiar el cliente futuro a `max_completion_tokens` tras la prueba de compatibilidad [S18].

Medir recursos de Mosquitto, API, cámara/YOLO y LiteRT-LM, incluido el costo residente. Documentar normalización de CPU: 100% de un núcleo frente a 100% del equipo completo. Evitar contar memoria compartida dos veces al sumar RSS; reportar métrica de proceso y total de sistema con su limitación.

## 7. Potencia manual y energía: métodos separados

El autor registrará potencia en W desde la página cada cierto tiempo. Se propone una lectura cada 30 s, incluyendo inicio y final, como frecuencia inicial del piloto. Conservar el instante de observación y el de introducción; una lectura anotada tarde no pertenece automáticamente al momento en que se pulsa guardar. No se verificaron aquí resolución, exactitud ni actualización de pantalla del PMB05.

Con muestras W y tiempos reales se puede estimar energía por trapecios: `E_est_Wh = sum((P_i + P_(i+1))/2 * (t_(i+1)-t_i)/3600)`. Es una estimación de integración, no captura picos entre lecturas ni prueba precisión del instrumento. La página dibuja puntos observados y una línea de interpolación identificada como tal. La estimación acumulada es provisional mientras falten lecturas, incluida la del final.

Fijar una separación máxima admisible para integrar —candidato 60 s para un período nominal de 30 s— y no integrar ni extrapolar huecos mayores. Informar duración cubierta, duración total y política de huecos. Una lectura aislada de W no permite integrar; solo contador inicial/final tampoco da una curva de potencia.

El PDF reporta además contador con pasos de 0,01 kWh = 10 Wh. Guardar sus lecturas si se utilizan, pero una diferencia de cero pasos no significa consumo cero. Una diferencia sostenida de 2 W necesita 5 h para acumular un solo paso: cálculo ilustrativo, no resultado experimental. El método de potencia manual amplía la metodología escrita y debe describirse con sus límites.

No convertir CPU% o activaciones en Wh. No atribuir energía a cada llamada de segundos a partir de lecturas cada 30 s. Mantener fuente y periféricos constantes; el medidor cubre su entrada eléctrica, no la energía interna aislada del chip. Capturar video continuo para replay no reproduce el consumo de cámara bajo demanda. Ver contratos y CSV en [10](10-controles-y-csv.md).

## 8. Diseño de escenarios y análisis

Escenarios del PDF: región vacía, ingreso, salida, cambio de conteo, permanencia inmóvil, persona fuera de radar dentro de cámara, dato antiguo, falla de sensor/cámara y discrepancia resoluble/no resoluble. Agregar solicitudes sin necesidad visual para medir activaciones evitables.

Registrar confusores: luz, oclusión, distancia, cobertura, cámara calentada o no, temperatura de Pi, fuente, undervoltage, swap, procesos ajenos y estado frío/caliente del motor. Estos registros no constituyen exclusiones automáticas: fijar criterios antes del ensayo final y reportar exclusiones.

La unidad de réplica es la sesión cuando las ventanas están correlacionadas. Usar diferencias emparejadas e intervalos por sesión; bootstrap por sesión si el número lo permite. Con pocas sesiones reportar distribución y limitaciones, sin tratar cientos de ventanas como cientos de réplicas independientes. Una diferencia no significativa no demuestra equivalencia ni no inferioridad; margen de omisión/calidad debe predefinirse.

Se propone un bloque como repetición completa de A–D bajo un mismo guion y entorno: el análisis empareja las cuatro ejecuciones por `block_id`. Los bloques se distribuyen entre días y se registra `day_id` porque pueden compartir condiciones. Las muestras por segundo y los escenarios dentro de cada bloque no son réplicas independientes. La propuesta concreta es 4 bloques piloto y 20 bloques finales, ajustables antes de la prueba final según variabilidad y precisión necesarias; ver [11](11-escenarios-y-repeticiones.md).

## 9. Manifiesto por ejecución

Guardar versión/commit de software, `uv` y paquetes, SO/kernel, modelo/revisión/hash, precisión del bundle, detector/metadata/hash, perfiles de imagen, prompt/schema, parámetros de generación efectivos, política, TTL, límites, regiones, clock/boot ID, configuración MQTT y estado térmico inicial. No incluir tokens de acceso ni claves.

Versionar el conjunto de preguntas, anotaciones, reglas y criterios de evaluación. Separar piloto de prueba final. El frontend puede etiquetar y exportar; no debe permitir cambiar un umbral dentro de una sesión ya admitida sin crear otra configuración.

Agregar plan y eventos de fallos, lecturas manuales de potencia, método de integración, retención y diccionario CSV. El plan es inmutable; la disponibilidad de una fuente sí puede cambiar durante la sesión por una intervención registrada. No confundir ese cambio con editar la política.
