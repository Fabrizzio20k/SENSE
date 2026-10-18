# SENSE: investigación y plan del prototipo Python

Fecha de revisión: 17 de octubre de 2026. Estado: diseño, análisis descriptivo de telemetría e implementación Python escrita. La versión ampliada no se ejecutó por instrucción del autor; falta verificarla en la Raspberry. Guía de uso en [README de Python](../README.md) y alcance efectivo en [16](16-version-python.md).

Para continuar en otra sesión: [AGENTS.md de la raíz](../../AGENTS.md) reúne acuerdos vigentes, avance, criterios, archivos y próximos pasos.

## Decisión principal

Construir un backend Python con una FSM determinista, contexto con evidencia temporal, herramientas específicas y una API HTTP con eventos SSE. Mantener MQTT como entrada de sensores, YOLO/NCNN como herramienta de conteo y Gemma 4 E2B/LiteRT-LM como intérprete opcional. Una descripción directa de imágenes es una ruta adicional explícita, con costo y evaluación separados.

El modelo no debe dirigir todo el sistema: cuando una regla o una herramienta ya contesta, no hace falta una llamada generativa. La FSM decide si necesita adquirir información, ejecutar visión, interpretar o abstenerse. Thinking queda siempre desactivado. La página observa decisiones en vivo por SSE, controla fallos simulados, registra lecturas W y descarga CSV; el backend aplica y registra las intervenciones sin delegar la política al navegador.

## Lectura y alcance

Se extrajo el contenido de las 52 páginas de `main.pdf` y se revisaron visualmente las tablas metodológicas 3.1, 3.2 y 3.3 y la sección de energía. Referencias al PDF: se indican página física y página impresa, porque su numeración difiere.

PDF analizado: [main.pdf](main.pdf), reubicado por el autor en `python_prueba/docs/`. Se comprobó que conserva el hash del original; no se volvió a extraer ni revisar su contenido en este traspaso.

SHA-256 del original: `01d11cd74e23183d7a57f3d73c79ba06dfa91427d593498bfd69a756fe0a65be`.

La instrucción posterior del autor prevalece: el diseño es independiente del código Rust existente. La mención de Rust en el PDF se registra únicamente como una diferencia documental pendiente. No se propone migrar, ampliar ni reutilizar la TUI existente.

Esto es una investigación técnica dirigida, con fuentes primarias y análisis del protocolo de tesis. No es una revisión sistemática ni una certificación de los sensores. No se enviaron el PDF ni imágenes privadas a proveedores de inferencia externos.

## Documentos, en orden

| Documento | Qué resuelve |
|---|---|
| [01 — Requisitos derivados del PDF](01-requisitos-del-pdf.md) | Qué debe hacer el sistema, hipótesis, restricciones y diferencias con las pruebas actuales. |
| [02 — Arquitectura y FSM](02-arquitectura-fsm.md) | Responsabilidades, estados, guardas, presupuestos y concurrencia. |
| [03 — MQTT y contratos de evidencia](03-mqtt-y-contexto.md) | Cómo consumir lo ya publicado sin volver a implementar drivers. |
| [04 — Cámara, YOLO y visión directa](04-camara-y-vision.md) | Rutas visuales, revisión de los ejemplos, resoluciones y pruebas necesarias. |
| [05 — SLM y herramientas](05-slm-y-herramientas.md) | Invocación condicional de Gemma, thinking desactivado, validación y compatibilidad LiteRT-LM. |
| [06 — API y streaming](06-api-streaming.md) | Contratos HTTP/SSE y responsabilidades del frontend. |
| [07 — Evaluación y mediciones](07-evaluacion.md) | Comparadores A–D, variante visual, métricas, replay y energía. |
| [08 — Plan de construcción](08-plan-de-implementacion.md) | Pasos, pruebas de aceptación y decisiones que deben congelarse. |
| [09 — Fuentes y registro de investigación](09-fuentes.md) | Consultas, evidencia, límites y fuentes verificadas. |
| [10 — Controles y CSV](10-controles-y-csv.md) | Fallos por fuente, series de recursos, W manuales, energía estimada y formatos exportados. |
| [11 — Escenarios y repeticiones](11-escenarios-y-repeticiones.md) | Guion de diez escenarios, bloques A–D, piloto y número propuesto de pruebas. |
| [12 — Resumen directo](12-resumen-del-sistema.md) | Qué se construirá, qué verá el usuario y qué datos obtendrá. |
| [13 — Guía de medición](13-guia-de-medicion.md) | Operación paso a paso, guardas de activación, seguimiento de episodios y significado de A–D. |
| [14 — Umbrales y activación](14-umbrales-y-activacion.md) | Catálogo único de parámetros, candidatos existentes, valores pendientes y cómo fijarlos en piloto. |
| [15 — Análisis de línea base y desfases](15-analisis-linea-base.md) | 490 mensajes, cadencia real, radar, reglas de alineación temporal, candidatos de piloto y procedimiento reproducible. |
| [16 — Primera versión Python](16-version-python.md) | Implementación por responsabilidad, invariantes, candidatos operativos y verificación pendiente en la Pi. |
| [Pendientes para continuar](../../AGENTS.md#pendientes-de-medición-y-metodología) | Mediciones y decisiones por cerrar; el antiguo `questions.md` no está disponible en el repositorio observado. |

## Evidencia disponible frente a lo pendiente

**Comunicado por el autor:** Pi 5 de 8 GB; publicación MQTT de ambiente y presencia; captura con Picamera2; ejemplos YOLO26n/NCNN; Gemma 4 E2B responde por LiteRT-LM. Se observaron, en una ejecución compartida, 17,79 s para texto y 39,06 s para imagen. No son benchmarks controlados del sistema integrado.

**Verificado en fuentes:** SSE y reconexión por identificador; semántica MQTT de retención y duplicados; interfaces publicadas y código upstream de LiteRT-LM; exportación NCNN; documentación de cámara; antecedentes de FSM y calibración. Ver [fuentes](09-fuentes.md).

**Calculado sobre el registro del autor:** 490 mensajes completos en 984.938503 s; intervalo mediano 2.014112 s; 42 transiciones de modo radar y 4 de presencia binaria. Original, hash, exclusión de una última línea truncada, script, pruebas y CSV están en [15](15-analisis-linea-base.md). No se midieron latencia MQTT ni desfase entre relojes; los nuevos valores temporales son candidatos de piloto.

**Propuesto, todavía no medido:** política adaptativa, límites de activación, esquema contextual, API, tamaño óptimo de imágenes, mejora energética y superioridad del SLM frente a reglas. Los números operativos de los documentos son candidatos de piloto cuando así se indica.

## Qué conviene construir primero

Un ciclo completo sin SLM: ingerir MQTT, formar un snapshot, contestar presencia o ambiente por reglas, guardar eventos y transmitirlos al frontend. Después añadir conteo YOLO y, por último, interpretación SLM. Así cada coste adicional tiene un comparador y los fallos pueden atribuirse a una etapa.

Los controles de fallos, el muestreador automático y las exportaciones forman parte del prototipo de experimentación desde la etapa de API. La propuesta de prueba final es 20 bloques A–D, 80 ejecuciones y 10 escenarios por ejecución; su tamaño se revisa con el piloto antes de recoger resultados finales. Las W manuales permiten una estimación temporal documentada, no una medida continua de picos.

Para entender y ejecutar las mediciones, comenzar por [13 — guía de medición](13-guia-de-medicion.md). A–D son configuraciones, no situaciones físicas; no toda lectura o cambio invoca al SLM. Los perfiles finales deben definir objetivo, condiciones relevantes, vigencia, adquisición e interpretación antes de medir. Una salida puede dejar una comprobación programada en lugar de inventar una causa.
