# 11. Escenarios, repeticiones y argumento experimental

## 1. Propuesta concreta, sujeta al piloto

Se propone **4 bloques piloto y 20 bloques finales**. Un bloque contiene cuatro ejecuciones, A, B, C y D, con el mismo guion de escenas, preguntas, perfiles y fallos. Así cada bloque ofrece una comparación emparejada; una muestra de CPU por segundo no constituye una repetición.

Esto es una propuesta de carga de trabajo y cobertura, no un cálculo de potencia estadística ya validado. El tamaño final se fija antes de recoger la prueba final, usando variabilidad del piloto, diferencia mínima relevante y recursos disponibles. No existe un número universal que garantice una tesis concluyente.

La unidad primaria de comparación es `block_id`; dentro de cada bloque están `run_id` por variante, episodios y escenarios. Los bloques se reparten entre días y se conserva `day_id` para no fingir independencia si comparten condiciones.

El procedimiento operativo está en [13 — guía de medición](13-guia-de-medicion.md): qué hace el investigador, qué automatiza el software, cuándo se activa cada componente y cómo se cierran o siguen los episodios. Un mismo guion no obliga a que todos los escenarios activen cámara o SLM ni produzcan diferencias entre A–D.

## 2. Piloto separado de la prueba final

| Elemento | Propuesta |
|---|---|
| Espacios | Un aula y un laboratorio. |
| Bloques | 2 por espacio, en días/condiciones diferentes cuando sea posible: 4 en total. |
| Variantes por bloque | A, B, C, D. |
| Duración dirigida inicial | Aproximadamente 10 min por variante para pruebas seleccionadas; no pretende recorrer todo el guion final. |
| Total | 16 ejecuciones y aproximadamente 160 min de medición dirigida, más preparación. |

El piloto prueba los diez escenarios repartidos entre bloques, capacidades del modelo, selección de resolución, TTL, tiempos, cola y carga del operador para anotar W. Sus datos no entran en el resultado final. Si cuatro bloques no permiten estimar razonablemente variabilidad o estabilidad, ampliar el piloto antes de congelar parámetros.

El piloto también decide si una intervención cabe en la duración prevista: una imagen puede tardar 40 s y una recuperación exige muestras nuevas. No acortar artificialmente el plazo para fabricar un fallo ni extenderlo solo para una variante.

## 3. Guion final de diez escenarios

Todas las variantes reciben los mismos tipos de consulta en los mismos momentos relativos. Presencia se etiqueta en la región comprobada, conteo solo donde es visible. Los eventos humanos y referencias no se muestran al modelo.

| ID | Escenario / intervención | Qué se espera observar | Qué permite argumentar |
|---|---|---|---|
| S01 | Región vacía y estable; consulta de presencia | Radar suficiente, datos vigentes, decisión explícita de no activar componentes innecesarios en C/D | Costo y falsas alarmas en estado estable. |
| S02 | Ingreso, variación de cantidad y salida según guion | Presencia y conteos en consultas fijadas; tiempos de cambio y omisiones | Respuesta a transiciones y exactitud de conteo. |
| S03 | Persona casi inmóvil dentro de región comparable | Persistencia de detección; conteo si se solicita, no cámara por cada lectura | Dependencia de movimiento y estabilidad del contexto. |
| S04 | Persona visible fuera de cobertura radar comprobada | Fuentes no comparables conservan su alcance; consulta visual explícita | Evitar afirmar aula vacía a partir de radar negativo. |
| S05 | Variación ambiental observable o fixture marcado; presencia controlada | Diferencia numérica y antigüedad correctas, sin causa inventada | Integración de ambiente y límites de inferencia. |
| S06 | Radar `disabled`, 45 s y restauración | Indisponibilidad inmediata, salida parcial o uso pertinente de visión, recuperación con dato nuevo | Degradación/reacción a una fuente declarada fuera de servicio. |
| S07 | SHT40 o ENS160 `disabled`, 45 s y restauración | Fuente afectada aislada; otras fuentes del payload continúan | Fallo parcial de telemetría sin perder todo el mensaje. |
| S08 | Cámara indisponible/error antes de consulta de conteo, luego restauración | No inventar cero; respuesta parcial/abstención; sin bucles | Manejo de percepción indispensable fallida. |
| S09 | Pérdida silenciosa/congelamiento de radar u otra fuente más allá del TTL | Último dato envejece, se detecta obsolescencia y se renueva al restaurar | Diferenciar silencio, dato antiguo e indisponibilidad explícita. |
| S10 | Evidencia radar/visión discordante en fixture temporal y espacialmente comparable | Se conserva discrepancia y sus límites; reglas/SLM no inventan resolución | Interpretación con evidencia contradictoria y abstención. |

Para S07 alternar SHT40 y ENS160 de forma balanceada entre los diez bloques de cada espacio: cinco de cada uno. A–D usan la misma fuente dentro del bloque. Esto da diez bloques finales por sensor en total; no afirmar veinte repeticiones de cada sensor.

S09 necesita durar más que el TTL congelado; S06/S08 deben permitir observar recuperación. Los 45 s son candidatos, no valores finales. Si S10 no se observa de forma natural, usar el mismo fixture identificado en todas las variantes y reportarlo en el estrato sintético. S04 solo se ejecuta físicamente si la geometría permite esa separación; no inventar la cobertura. Si no es posible, declararlo no evaluable o evaluar su contrato mediante replay separado, sin contarlo como escena física.

No calentar sensores con llama para generar datos de tesis. S05 puede usar una variación segura y autorizada o datos registrados/fixtures claramente identificados; ninguna opción verifica por sí sola exactitud física ni causalidad.

## 4. Repeticiones finales y tiempo de trabajo

| Elemento | Propuesta base |
|---|---:|
| Bloques por espacio | 10 |
| Espacios | 2 |
| Total de bloques | 20 |
| Configuraciones por bloque | 4 |
| Ejecuciones A–D | 80 |
| Escenarios por ejecución | 10 |
| Presentaciones planificadas de escenario | 800 |
| Repeticiones por escenario y variante, sumando espacios | 20, si todos son evaluables |
| Repeticiones por escenario/variante/espacio | 10, si todos son evaluables |
| Duración puntuada candidata por ejecución | 20 min, aproximadamente 2 min por escenario |
| Tiempo puntuado total | 26 h 40 min, más calentamiento, reposición y pausas |

800 presentaciones no son 800 réplicas independientes: comparten bloque, espacio y día. Diez escenarios tampoco significan diez eventos exactos; S02 puede tener varios eventos de referencia. Registrar el número efectivo y no reemplazar no evaluables por aciertos.

Distribuir los diez bloques de cada espacio entre al menos cinco días cuando sea viable. Equilibrar orden de A–D, iluminación y condiciones iniciales. Puede usarse un esquema de orden balanceado de cuatro secuencias repetidas cinco veces sobre los 20 bloques; generar el orden antes de medir y conservar la semilla/plan.

Antes de cada variante, restaurar condiciones físicas/overrides y esperar una línea base definida. A–D comparten perfil de cámara y estado de modelo inicial según el tratamiento. Guardar fase `warmup` y fase `scored`; informar costo de arranque además del estable, no borrarlo del trace ni de la energía total. Si el guion requiere más de 20 min, fijar la nueva duración para todas las variantes antes del ensayo final.

Si solo se pueden realizar 10 bloques totales, son 40 ejecuciones y unas 13 h 20 min puntuadas. Es un alcance menor que debe declararse, especialmente en análisis por espacio y eventos raros; no es equivalente al plan de 20 bloques.

## 5. Número final y precisión de las conclusiones

Para una diferencia media emparejada puede hacerse una aproximación inicial con `n ≈ ((1.96 + 0.84) * s_d / delta)^2`, donde `s_d` es la desviación de diferencias entre bloques y `delta` la diferencia mínima relevante. Corresponde a aproximación normal bilateral al 5% y potencia 80%, no a una garantía para datos pequeños o dependientes [S24, S25].

Ejemplo ilustrativo: si `delta=0.5*s_d`, la aproximación da 32 bloques; si `delta=s_d`, da 8. Por eso 20 bloques es una propuesta inicial de trabajo, no una justificación automática para detectar efectos moderados. Para F1, proporciones acotadas, omisiones y no inferioridad, el cálculo debe ajustarse al tipo de resultado y a agrupación por sesión/día; no trasladar mecánicamente esa fórmula.

Antes de la prueba final elegir endpoints primarios: activaciones visuales/hora y omisiones para H2; respuesta sustentada y afirmaciones sin respaldo para H3. Definir margen máximo de empeoramiento admisible, tratamiento de comparaciones múltiples y precisión buscada. Tras el piloto, aumentar/reducir bloques según criterio fijado o declarar alcance descriptivo si los recursos no permiten potencia suficiente. No añadir sesiones hasta obtener un p favorable.

Las repeticiones dentro de un día pueden ser correlacionadas; analizar por espacio y bloque, con día como agrupación adicional cuando corresponda. Con pocos días, presentar esa limitación y no prometer intervalos fiables por remuestreo fino. Un resultado sin diferencia detectable no prueba equivalencia.

## 6. Prueba aislada de reglas frente a SLM

Además del sistema en vivo, seleccionar antes de evaluar **cinco preguntas/snapshots por bloque final**, cubriendo dato suficiente, dato faltante, dato antiguo, discrepancia e interpretación ambiental acotada. Son 100 pares pregunta–snapshot para 20 bloques.

Cada par lo resuelven C (reglas) y D (Gemma con thinking desactivado), sin nueva adquisición: **200 respuestas a calificar**. El snapshot es idéntico y se agrupa estadísticamente por bloque; los 100 pares no son 100 sesiones independientes. Evitar casos ajustados durante el piloto. Duplicar la calificación humana de, por ejemplo, 25% del corpus elegido aleatoriamente y reportar acuerdo/discrepancias antes de adjudicar.

La interpretación libre puede costar más y no aportar exactitud. También es un resultado válido que las reglas sean suficientes para una parte importante del catálogo.

Esta prueba aislada invoca ambos intérpretes deliberadamente para medir su capacidad sobre un corpus. No representa que la política D deba invocar al SLM en todos esos casos en vivo; sus llamadas reales y costos de política se calculan a partir de las ejecuciones operacionales por separado.

## 7. Prueba opcional de visión directa

Si se conserva `E_visual`, hacer un ensayo separado: 20 imágenes nuevas que cubran escenas simples, varias personas, oclusión, luz difícil y detalle textual; tres tamaños de envío 320/480/640; dos pasadas con orden de tamaños balanceado: **120 llamadas**. Es una prueba exploratoria de latencia/repetibilidad y utilidad, no un nuevo tamaño de muestra independiente de 120 escenas.

Separar primera carga visual de motor caliente. No sumar estos tiempos/energía a A–D ni usar la descripción de Gemma como referencia verdadera del conteo. Si la visión directa no es requisito final, se puede omitir esta rama sin perder el experimento principal.

## 8. Qué resultados permiten defender el sistema

- **Calidad:** presencia/conteo y preguntas respaldadas por evidencia, con cobertura y abstenciones explícitas.
- **Adaptación:** C/D usan menos activaciones que A sin superar el margen de omisiones definido.
- **Aporte del SLM:** D mejora o no frente a C en el corpus idéntico, con costo adicional medido.
- **Robustez:** indisponibilidad, dato antiguo y recuperación se manejan sin inventar mediciones.
- **Recursos:** series CPU/RAM, latencia y número de inferencias por fase y escenario.
- **Potencia:** puntos W, duración cubierta y energía estimada con límites del muestreo; contador aparte si resuelve diferencias.

Las conclusiones se restringen al montaje, escenas y condiciones ensayadas. La web y los CSV facilitan observar y analizar; no sustituyen anotación independiente, repetición ni explicación de incertidumbre.
