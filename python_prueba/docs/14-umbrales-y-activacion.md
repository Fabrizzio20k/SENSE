# 14. Catálogo de umbrales y condiciones de activación

## Estado real de la definición

Se han definido las clases de condición en [13, sección 2](13-guia-de-medicion.md), las guardas en [02](02-arquitectura-fsm.md), valores candidatos de instrumentación en [10](10-controles-y-csv.md) y candidatos temporales fundamentados en el registro de 490 mensajes en [15](15-analisis-linea-base.md). **La primera versión Python contiene una configuración candidata; todavía no existe un perfil numérico calibrado.** Este catálogo centraliza mediciones, propuestas y pendientes sin presentarlos como resultados de evaluación del sistema integrado.

Cada parámetro del perfil futuro debe guardar valor, unidad, estado (`pilot_candidate` o `frozen`), procedencia y versión. Un valor pendiente es `null` explícito; no cero ni un default oculto. No se admite una sesión final si faltan parámetros aplicables a su objetivo y variante.

**Actualización de implementación:** la primera versión ya contiene estos umbrales y un perfil operativo candidato en `context.py`. [16](16-version-python.md) documenta su procedencia y las pruebas pendientes. Como valores iniciales ejecutables se eligieron visión periódica/TTL visual de 30 s, cooldown 5 s, timeouts visual/SLM de 90/120 s, episodio 240 s, cola 8 y hasta dos seguimientos cada 30 s durante 180 s. Las filas pendientes de piloto se refieren a su calibración definitiva; la versión escrita aún no se ejecutó en la Pi. El TTL físico por sensor y el desfase radar–cámara continúan desconocidos.

## 1. Detección de cambios y vigencia

| Parámetro | Qué controla | Estado / dato necesario |
|---|---|---|
| `source_period_s[source]` | Cadencia real de cada productor | Mediana del sobre MQTT: 2.014112 s en 489 intervalos; máximo 2.020576 s. Medición descriptiva, no período de adquisición por sensor. |
| `telemetry_silence_s` | Watchdog de recepción del sobre MQTT completo | Candidato: 7 s, tres intervalos máximos observados más 0.938272 s de margen elegido. No es TTL ni detector de lectura interna congelada. |
| `source_ttl_s[source,task]` | Cuándo un dato deja de ser vigente para la tarea | Pendiente: cadencia, retrasos y antigüedad aceptable; no igual para todos los sensores. |
| `baseline_window_s[metric]` | Ventana de referencia del indicador | Candidato: 120 s anteriores a la ventana reciente, sin solapamiento. Elección de piloto, no estación ambiental demostrada. |
| `recent_window_s[metric]` | Ventana reciente que se compara con la referencia | Candidato: 30 s; mediana de aproximadamente 15 observaciones con la cadencia observada. |
| `min_valid_samples[metric]` | Evidencia mínima para comparar ventanas | Candidatos: 12 recientes y 48 de referencia, aproximadamente 80% nominal. Exigir además cobertura temporal; no rellenar huecos. |
| `change_delta[metric]` | Diferencia mínima que abre un evento | Piloto: temperatura 0.5 °C, humedad 3 pp, TVOC 50 ppb, eCO2 100 ppm; diferencia absoluta entre medianas. Ver perfil inicial debajo. |
| `persistence_s[metric]` | Cuánto debe mantenerse el cambio antes de considerarlo relevante | Candidato: 10 s con evidencia nueva y cobertura; aproximadamente seis evaluaciones para abarcar ese tiempo. Falta evaluar omisiones/demora. |
| `recovery_delta[metric]` | Banda de retorno; debe ser menor que el umbral de apertura | Piloto: temperatura 0.25 °C, humedad 1.5 pp, TVOC 25 ppb, eCO2 50 ppm, respecto de la referencia conservada. |
| `recovery_persistence_s[metric]` | Estabilidad necesaria para registrar retorno | Candidato: 20 s con evidencia nueva y cobertura temporal. |
| `presence_debounce_s` | Estabilidad para aceptar una transición radar | Candidato: 2 s, dos o más observaciones concordantes que abarquen ese tiempo; mapear 0 a ausencia y 1/2/3 a presencia. Falta referencia humana y prueba de eventos breves. |
| `crossmodal_max_skew_s` | Separación temporal máxima para comparar radar y visión | Pendiente: tiempos de captura/medición y tolerancia de la tarea. |

Los umbrales ambientales son de **cambio experimental**, no límites de seguridad ni identificación de sustancias. ENS160 debe tener calidad válida; eCO2 no se transforma en CO2 medido ni en identificación de butano.

Justificación, fórmulas, costes temporales y límites de los candidatos: [15, sección 7](15-analisis-linea-base.md#7-candidatos-temporales-para-el-piloto). La referencia al inicio exige historia de 150 s; una fuente sin calidad suficiente no se convierte en válida por acumular muestras. Apertura y recuperación ya tienen valores iniciales, todavía sin calibrar; TTL y desfase entre modalidades siguen pendientes. No hay perfil completo para ensayo final.

### Perfil ambiental inicial confirmado para el piloto

Sea `D = mediana_reciente − mediana_referencia`. La ventana reciente dura 30 s y la referencia los 120 s inmediatamente anteriores a ella. Para cada magnitud se abre un episodio si `abs(D) >= apertura` durante al menos 10 s, con muestras nuevas suficientes y cobertura temporal. Se detectan tanto subidas como bajadas; el signo se conserva en el evento.

| Magnitud | Apertura: cambio mínimo sostenido | Retorno: diferencia absoluta máxima |
|---|---:|---:|
| Temperatura | 0.5 °C | 0.25 °C |
| Humedad relativa | 3 puntos porcentuales | 1.5 puntos porcentuales |
| TVOC | 50 ppb | 25 ppb |
| eCO2 estimado | 100 ppm | 50 ppm |

La banda de retorno se debe cumplir durante 20 s, respecto de la referencia conservada para el episodio. Un episodio abierto no se vuelve a abrir por cada publicación. La recuperación indica retorno del indicador, no ausencia de riesgo. Este perfil no añade límites absolutos de seguridad ni transforma AQI en un disparador separado.

**Procedencia de la elección:** son valores redondos de ingeniería para empezar con cambios sostenidos de mayor amplitud que los saltos aislados observados (máximos 0.07 °C, 0.22 pp, 36 ppb y 67 ppm). Esa comparación solo aporta contexto de escala: el umbral se aplica a medianas de ventanas, no a diferencias entre dos muestras. No fueron obtenidos por optimización, especificación de exactitud del fabricante ni validación con eventos etiquetados. La banda de retorno de la mitad y los 20 s son decisiones de histéresis para probar. Pueden omitir cambios pequeños o lentos; el piloto debe medirlo antes de congelarlos. Estado de todo este perfil: `pilot_candidate`.

Regla candidata sencilla: comparar la mediana de ventana reciente con una referencia estable, exigir `change_delta` y persistencia con muestras suficientes. Si faltan datos durante el intervalo, no contar ese silencio como persistencia confirmada. Conservar la referencia al abrir el evento para que una subida sostenida no desaparezca por incorporar inmediatamente el evento a su propia línea base.

La recuperación se evalúa con su banda y duración; regresar a la referencia significa retorno del indicador, no confirmación de ausencia de riesgo. La ventana y el método de referencia también son parámetros del experimento y se congelan antes de la prueba final.

## 2. Activación visual y límites de ejecución

| Parámetro o condición | Estado inicial |
|---|---|
| `periodic_vision_interval_s` de A | Pendiente de piloto; los 30 s usados al explicar el flujo eran un ejemplo. |
| `simple_triggers` de B | Candidato: transición radar ausencia → presencia. Debe fijarse la lista exacta; no añadir renovaciones ocultas. |
| `count_required` y región de conteo | Pendiente por objetivo: a demanda o mantenimiento de conteo con antigüedad máxima definida. |
| `visual_count_ttl_s` | Pendiente: tiempo aceptable sin renovar conteo y costo de visión en la Pi. |
| `vision_cooldown_s` | Pendiente: latencia medida y tasa de activación tolerable. |
| `max_visual_calls_per_episode` | Candidato ya propuesto: 1 trabajo visual. Mosaicos se cuentan además como inferencias del detector. |
| `heavy_action_concurrency` | Candidato: 1 acción pesada simultánea. |
| Timeouts de cámara, YOLO y SLM | Pendientes: medir frío/caliente y margen; no fijarlos por debajo de una ejecución legítima conocida. |
| `episode_deadline_s`, intervalo/máximo/plazo de seguimientos | Pendientes de objetivo y piloto. Límite finito obligatorio. |
| Límite de cola y reservas de memoria/condición térmica | Pendientes del sistema integrado; medir consumo y latencias antes de elegirlos. |
| Score YOLO y fusión de mosaicos | `conf=0.15` e IoU `0.45` proceden del ejemplo del autor; candidatos sin calibrar, no valores finales. |

En C/D, activar visión requiere conjuntamente: necesidad visual definida, evidencia ausente/vencida o corroboración pertinente, región cubierta, cámara disponible, cooldown cumplido y presupuesto suficiente. Un incremento ambiental por sí solo no satisface esa guarda.

Si el objetivo exige conteo vigente, su vencimiento puede activar visión aunque el radar no cambie. Si el objetivo pide solo presencia radar, no se crea una necesidad de conteo por defecto. Si el presupuesto impide observar, se registra la limitación; no se presenta como pregunta resuelta.

## 3. Invocación del SLM: una guarda, no un único número

Propuesta de lista inicial de tipos interpretativos: `environment_change_persistent` y `crossmodal_conflict`, además de una pregunta de interpretación programada explícitamente en el guion. La lista se valida en piloto y se congela por perfil; no está implementada todavía.

Para invocar Gemma se deben cumplir **todas** estas condiciones:

1. Variante D y tipo interpretativo habilitado.
2. Pregunta que necesita interpretación; una lectura, resta o conteo directo no basta para justificarla.
3. Snapshot suficiente para esa pregunta, con calidad, tiempos y alcance explícitos. Un conflicto requiere que las fuentes sean realmente comparables.
4. No se ha interpretado ya la misma evidencia relevante sin un cambio o solicitud que justifique otra llamada.
5. No se agotaron llamadas, cooldown, recursos ni plazo.

`max_slm_calls_per_episode=1` y cero reintentos generativos automáticos son candidatos ya propuestos. El cooldown y el límite de salida efectivo siguen pendientes de prueba. Thinking es siempre falso; no es un umbral ni una opción para el investigador.

Si faltan lecturas, primero corresponde adquirirlas o declarar la limitación. Gemma no se activa para suplir mediciones desconocidas con una explicación plausible. Las cuatro variantes detectan los mismos tipos de cambio ambiental mediante reglas; D añade interpretación cuando su guarda se cumple.

## 4. Valores propuestos que no son umbrales de activación

| Valor | Función y estado |
|---|---|
| Recursos cada 1 s | Cadencia candidata de instrumentación. |
| W manuales cada 30 s | Cadencia candidata del operador; puede pasar a 60 s tras piloto si se congela para todos. |
| Máximo de hueco para integrar W: 60 s | Candidato ligado a período nominal de 30 s; no se aplica sin revisar si cambia ese período. |
| Fallos de 45 s | Duración ilustrativa de intervención, no criterio ambiental. |
| Imágenes de 480 en lado mayor | Candidato para envío a Gemma; no prueba una resolución interna ni menor costo. |

Ninguno de esos números significa «llamar a Gemma cada 30 segundos».

## 5. Qué falta obtener y cómo cerrar el perfil

1. **Contrato y cadencia observados:** el registro posterior aporta 490 mensajes completos en 984.938503 s, los cuatro códigos radar y 489 intervalos; ver [15](15-analisis-linea-base.md). Faltan semántica temporal, calidad/fallos y adquisición por sensor; los pendientes documentados están en [AGENTS.md](../../AGENTS.md#pendientes-de-medición-y-metodología). El antiguo `questions.md` no está disponible en el repositorio observado. No se dispone de tiempos de recepción para medir latencia o desfase entre relojes.
2. **Línea base analizada:** se conservaron original, hash, cola excluida, script y resultados. La temperatura cambia −0.78 °C y humedad +2.65 pp entre extremos; no se trata la variabilidad global como ruido estacionario. Completar sesiones con estabilización/calidad verificadas, condiciones anotadas y eventos de referencia; una sesión no representa todos los días/espacios.
3. **Latencia integrada:** medir cámara, detector y SLM, tanto primera carga como caliente, junto a ingesta e instrumentación. Eso permite elegir TTL, plazos y cooldown compatibles.
4. **Objetivo operativo:** decidir qué preguntas deben contestarse, cuán actual debe ser el conteo y cuánto retraso/omisión es aceptable. Q05, Q07 y Q08.
5. **Selección en piloto:** probar candidatos de umbral con secuencias etiquetadas, registrar falsos disparos, eventos omitidos y tiempos. Elegir por un criterio fijado, no por qué configuración sale favorecida.
6. **Congelamiento:** guardar valores, unidades, método, evidencia del piloto y hash de perfil; mantener reglas compartidas iguales en A–D. La prueba final no ajusta parámetros sobre la marcha.

No hace falta completar todo para empezar a implementar infraestructura y validadores. Sí hace falta un perfil candidato completo para probar la política, y un perfil congelado para medir resultados finales. Este documento define el catálogo; no sustituye esas mediciones ni aporta calibración inexistente.
