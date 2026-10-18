# 09. Fuentes, método y registro de investigación

Fecha de consulta: 17 de octubre de 2026. Tipo de trabajo: investigación técnica dirigida para diseño y evaluación de SENSE; no revisión sistemática ni auditoría completa de la bibliografía del PDF.

## 1. Cómo se investigó

1. Se identificó `main.pdf` originalmente en la raíz, se extrajeron sus 52 páginas y se registró su hash. Se revisaron objetivos, límites, capítulos II–III y comparadores; las tablas metodológicas y la energía se contrastaron con renderizados de las páginas. El autor lo reubicó después en `python_prueba/docs/main.pdf`; se comprobó que conserva el hash del original.
2. Se separaron requisitos documentales, observaciones comunicadas por el autor y propuestas de ingeniería. La instrucción de diseñar independientemente en Python reemplaza cualquier condicionamiento del repositorio Rust.
3. Se revisaron los ejemplos pegados por el autor como datos: captura, exportación NCNN, mosaicos, NMS y paths MQTT. No se asumió que estuvieran presentes como archivos ejecutables ni se modificaron.
4. Se buscaron documentación primaria de MQTT/SSE/cámara/NCNN, fuentes académicas de FSM/agentes/calibración y documentación de LiteRT-LM.
5. Para capacidades que la guía de API no detalla, se inspeccionó código upstream público de LiteRT-LM: handlers de completions, parsers y ciclo de vida del motor. Esas observaciones están ligadas a la rama consultada, no al paquete de la Pi.
6. Se diseñaron contratos y comparaciones que permitan invalidar las hipótesis, no solo demostrar una interfaz funcionando. Las dudas se trasladaron inicialmente a `questions.md`, archivo no disponible en el estado observado del repositorio. Los pendientes actuales documentados se resumen en [AGENTS.md](../../AGENTS.md#pendientes-de-medición-y-metodología).
7. Se hizo revisión interna de límites y coherencia. No hubo revisión por un segundo investigador o modelo independiente; no se presenta como tal.
8. Tras la aclaración del autor se añadieron contratos de controles de fallos, series de recursos/CSV y W manuales; thinking activado se retiró del alcance. Se corrigieron rutas tras mover la carpeta a `python_prueba/docs`. El plan de 20 bloques es una propuesta de trabajo, no una muestra con potencia ya demostrada.
9. Se preservó y analizó el registro textual posterior de 490 mensajes completos, excluyendo explícitamente una cola incompleta. [15](15-analisis-linea-base.md) registra hash, procedimiento, resultados y decisiones temporales; los números calculados son descripción de esa sesión, no mediciones de latencia integrada ni validación de umbrales.

### Consultas utilizadas, ejemplos representativos

- `site.docs.ultralytics.com integrations ncnn export arguments half imgsz YOLO26 quantize`
- `site.github.com/google-ai-edge/LiteRT-LM thinking tool_calls chat_template_kwargs`
- `site.html.spec.whatwg.org server sent events Last-Event-ID eventsource`
- `site.docs.oasis-open.org mqtt retained message duplicate qos 1 timestamp`
- `site.raspberrypi.com documentation picamera2 manual capture SensorTimestamp`
- `site.techscience.com/cmc/v87n2/66586 LEAF finite state machine`

No se enviaron fragmentos del manuscrito a motores de inferencia externos. La búsqueda usó términos técnicos y metadatos públicos. No se ejecutaron clientes de proveedores académicos ni revisiones cruzadas de pago.

### Criterios de selección y exclusión

Preferencia por especificaciones normativas para transporte, documentación/código del proveedor para API y hardware, y publicaciones originales para conceptos de agentes y calibración. Se excluyeron como prueba de rendimiento de esta Pi las cifras de GPUs externas, teléfonos y ensayos con modelos o cargas distintas. Una guía de despliegue no demuestra superioridad experimental de SENSE.

No se contabilizan registros como un flujo PRISMA ni se afirma exhaustividad. Los trabajos bibliográficos del PDF se usan para interpretar su argumento; solo los que aparecen abajo fueron contrastados específicamente para este diseño.

## 2. Registro de fuentes primarias

### S00. Documento del autor

[main.pdf](main.pdf). Hash registrado en el README. Autoría y datos de portada conservados en el original. Requisitos principales: objetivos (PDF 10–14), semántica contextual (28–35), metodología (38–48). Aporta autoridad sobre el protocolo propuesto, no evidencia de resultados ya medidos.

### S01. Configuración de LiteRT-LM

Google AI Edge. [CLI Configuration](https://developers.google.com/edge/litert-lm/cli/configuration).

Verificado: defaults y configuración por modelo; campos de backend, visión, hilos, contexto, thinking y especulación. Uso: diseñar perfiles y pruebas de configuración efectiva. Límite: que un campo esté documentado no demuestra que todos los caminos de una versión lo apliquen.

### S02. Servidor LiteRT-LM

Google AI Edge. [OpenAI-Compatible Server](https://developers.google.com/edge/litert-lm/cli/openai_server).

Verificado: registro local de modelos, servicio de completions y streaming. Uso: conservar el servidor existente como dependencia local. Límite: no es una API de experimentos, ni garantiza UI web, cancelación completa, autenticación o paridad con todos los parámetros de otros servidores.

### S03. Exportación NCNN

Ultralytics. [YOLO NCNN Export](https://docs.ultralytics.com/integrations/ncnn).

Verificado: parámetros `imgsz` y `quantize`; FP16 con valor 16; ejecución CPU y ruta Vulkan documentada. Uso: revisar exportación y precisión del ejemplo. Límite: no demuestra que el export concreto cambie de tamaño a 640 ni acelere con la GPU de esta Pi.

### S04. YOLO26

Ultralytics. [YOLO26](https://docs.ultralytics.com/models/yolo26).

Verificado: familia y diseño de detección end-to-end sin NMS. Uso: distinguir inferencia por imagen de fusión global entre mosaicos. Límite: exactitud del conteo, falsas detecciones y conveniencia de los umbrales deben evaluarse en las escenas de tesis.

### S05. Semántica MQTT

OASIS. [MQTT 5.0](https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html) y [MQTT 3.1.1](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/mqtt-v3.1.1.html).

Verificado: retención y posibilidad de duplicados según nivel de entrega. Uso: no confundir retención con frescura ni QoS con deduplicación semántica. Límite: aún no se conoce versión/QoS/configuración del productor real.

### S06. Cliente MQTT Python

Eclipse Paho. [Client module](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).

Verificado: callbacks, conexión y bucle de red. Uso: suscripción única y transferencia de trabajo fuera del callback. Límite: la librería no define el esquema del productor ni las reglas de calidad de SENSE.

### S07. Cámara y tiempos

Raspberry Pi. [The Picamera2 Library](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf) y [Camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html#picamera2).

Verificado: adquisición y metadatos de cámara, incluido `SensorTimestamp`. Uso: correspondencia píxeles/tiempo y perfil de captura. Límite: configuración óptima, estabilización y correspondencia de relojes se verifican en la Pi; no se benchmarkeó aquí.

### S08. Trabajo bloqueante y cancelación Python

Python Software Foundation. [Coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html).

Verificado: tareas, timeouts y ejecución en hilos. Uso: separar API de operaciones bloqueantes. Límite de diseño: cancelar la espera de una coroutine no garantiza detener código nativo que ya ejecuta en otro hilo; se requiere comprobar o aislar el worker.

### S09. Ciclo de vida de la API

FastAPI. [Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).

Verificado: inicialización y cierre de recursos compartidos mediante lifespan. Uso: un dueño de cliente MQTT y tareas de monitoreo. Un solo worker durante el prototipo es una decisión de diseño para evitar duplicación de hardware, no una limitación general de FastAPI.

### S10. Persistencia

SQLite. [Write-Ahead Logging](https://www.sqlite.org/wal.html).

Verificado: coexistencia de lectores/escritor y restricciones de WAL. Uso: registro local con transacciones cortas. Límite: WAL no crea una base distribuida ni elimina el límite de un escritor a la vez.

### S11. Streaming SSE

WHATWG. [Server-sent events, HTML Standard](https://html.spec.whatwg.org/multipage/server-sent-events.html).

Verificado: formato de eventos, identificadores, reconexión y `Last-Event-ID`. Uso: flujo de progreso recuperable. Persistencia, idempotencia del comando y retención son responsabilidad de SENSE; no garantías automáticas del transporte.

### S12. Concurrencia entre hilos

Python Software Foundation. [Developing with asyncio](https://docs.python.org/3/library/asyncio-dev.html#concurrency-and-multithreading).

Verificado: gran parte de los objetos asyncio no son seguros entre hilos y existen mecanismos de transferencia al event loop. Uso: puente desde callbacks Paho. Límite: la política de cola y pérdida es parte de la aplicación.

### S13. Resolución visual de Gemma

Google. [Image understanding](https://ai.google.dev/gemma/docs/capabilities/vision/image).

Verificado: presupuestos visuales configurables en el procesamiento general de Gemma 4. Uso: no equiparar resolución JPEG con costo fijo de inferencia. Límite: la guía usa otra interfaz y no demuestra qué opciones están expuestas o fijadas en el bundle `.litertlm` de la Pi.

### S14. Calibración

Guo, C., Pleiss, G., Sun, Y., y Weinberger, K. Q. (2017). [On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a.html). PMLR, 70, 1321–1330.

Verificado: distingue scores/confianza de probabilidades empíricamente calibradas. Uso: evitar disparadores basados en una confianza generada sin validación. Límite: no es una calibración de YOLO26 ni Gemma en este montaje.

### S15. FSM y expertos SLM en IIoT

Yang, Q. et al. (2026). [LEAF: A Lightweight Edge Agent Framework with Expert SLMs for the Industrial Internet of Things](https://www.techscience.com/cmc/v87n2/66586). Computers, Materials & Continua, 87(2), 30. DOI: [10.32604/cmc.2025.074384](https://doi.org/10.32604/cmc.2025.074384).

Verificado en página editorial y resumen: expertos de planificación, ejecución e interacción, adaptación y control FSM. Uso: antecedente de separar control e interpretación. No se revalidaron aquí los porcentajes, benchmarks o todo el método del artículo; no se extrapolan sus resultados a la Pi.

### S16. Razonamiento y acciones

Yao, S. et al. (2023). [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629).

Verificado en resumen/versionado: alternancia entre razonamiento y acciones en tareas de lenguaje e interacción. Uso: contraste conceptual con una FSM de herramientas específicas. Límite: no prueba beneficio ni costo aceptable para Gemma E2B en sensores reales.

### S17. ENS160

ScioSense. [ENS160 datasheet, versión 1.3](https://www.sciosense.com/wp-content/uploads/2023/12/ENS160-Datasheet.pdf), fecha de portada 29 de marzo de 2023.

Verificado: eCO2 calculado, indicadores y secciones de calentamiento/estado. Uso: preservar semántica y calidad de las observaciones. No se revisó firmware ni montaje. La referencia del PDF usa otra descripción de edición; esta es la versión identificada por la portada consultada.

### S18. Implementación de chat completions

Google AI Edge. [openai_chat_completions.py](https://github.com/google-ai-edge/LiteRT-LM/blob/main/python/litert_lm_cli/commands/serve/openai_chat_completions.py).

Observado: herramientas proxy, `automatic_tool_calling=False`, streaming de llamadas, `max_completion_tokens` y configuración de conversación. Uso: diseñar un executor propio con validación y probar el límite real de salida. Límite: rama `main` mutable; no hay garantía de que coincida con el paquete instalado por uvx.

### S19. Parsers de parámetros

Google AI Edge. [openai_common.py](https://github.com/google-ai-edge/LiteRT-LM/blob/main/python/litert_lm_cli/commands/serve/openai_common.py).

Observado: parsing de `reasoning_effort`, salida JSON/schema, traducción de imágenes y cómputo de usage. Uso: prueba de capacidades y estructura de peticiones. Límite: no todos los esfuerzos representan presupuestos finos; compatibilidad exacta y semántica de tokens deben comprobarse localmente.

### S20. Ciclo de vida y configuración del motor

Google AI Edge. [util.py](https://github.com/google-ai-edge/LiteRT-LM/blob/main/python/litert_lm_cli/commands/serve/util.py) y [module.py](https://github.com/google-ai-edge/LiteRT-LM/blob/main/python/litert_lm_cli/commands/serve/module.py).

Observado: servidor HTTP, motor persistente y reinicialización según configuración. La construcción de `Engine` inspeccionada no pasa explícitamente el campo de hilos CPU. Uso: una sola ruta de cómputo y comprobación efectiva de hilos. No se declara un bug confirmado del paquete de la Pi a partir de esta lectura upstream.

### S21. Rendimiento externo: referencia, no garantía

Raspberry Pi (11 de agosto de 2026). [Mastering edge AI on Raspberry Pi with LiteRT and Gemma](https://www.raspberrypi.com/news/mastering-edge-ai-on-raspberry-pi-with-litert-and-gemma/).

Verificado: comparación publicada de Gemma E2B en CPU de Pi 5 de 8 GB. El artículo presenta cifras distintas para llama.cpp entre tabla principal y apéndice y no proporciona una medida equivalente de la latencia de la foto del autor. Uso: motivar una prueba, no prometer 9 tokens/s ni ahorro energético de SENSE.

### S22. Entorno de Picamera2

Raspberry Pi. [Repositorio Picamera2](https://github.com/raspberrypi/picamera2/blob/main/README.md).

Verificado: biblioteca ligada al stack libcamera y soporte de Raspberry Pi OS. Uso: revisar instalación e intérprete antes de integrar entornos uv. Límite: compatibilidad exacta de ABI y paquetes se conoce con la versión del sistema de la Pi.

### S23. Registro de recursos

psutil. [API](https://psutil.io/api/) y [FAQ](https://psutil.io/faq/).

Verificado: métricas de sistema/proceso, primera lectura incremental de CPU sin intervalo previo y distinción de CPU de proceso que puede superar 100%. Uso: especificar series temporales con unidades y valores ausentes explícitos. No todos los sensores/atributos están disponibles en cada SO; máximos muestreados no equivalen a picos continuos reales.

### S24. Tamaño de muestra y diferencia detectable

NIST/SEMATECH. [Sample sizes required](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm).

Verificado: relación entre tamaño, desviación, diferencia mínima, alfa y beta bajo aproximaciones indicadas. Uso: explicar por qué 20 bloques es una propuesta inicial y no garantía universal. La fórmula ilustrativa no calcula potencia de F1, omisiones agrupadas o no inferioridad.

### S25. Comparaciones emparejadas

NIST/SEMATECH. [Analysis of paired observations](https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm).

Verificado: análisis de diferencias entre observaciones emparejadas. Uso: comparar A–D por bloque en vez de contar muestras temporales correlacionadas como réplicas. Escenarios/días pueden añadir dependencia que requiere análisis agrupado y límites explícitos.

### S26. Registro de telemetría del autor

[Texto recibido el 17 de octubre de 2026](data/2026-10-17-baseline-recibido.txt). SHA-256 `2b47eda963f45490bedda4590f637f8cd6a700a47e6e0ee2f313c7eb920a3ce7`.

Verificado por análisis reproducible: 490 JSON completos del mismo dispositivo, 489 intervalos positivos, cuatro códigos radar y variaciones ambientales. Línea 491 incompleta excluida con diagnóstico. Uso: caracterizar cadencia, distinguir modo/presencia y fundamentar candidatos temporales. Límite: texto proporcionado, sin recepción, tramas radar, anotaciones, calidad ENS160 ni referencia temporal independiente; no valida sincronización, error físico ni detección. Procedimiento y artefactos en [15](15-analisis-linea-base.md).

## 3. Síntesis de evidencia y decisiones

| Pregunta de diseño | Evidencia disponible | Recomendación | Qué falta demostrar |
|---|---|---|---|
| ¿Usar streaming? | SSE tiene formato y reconexión; LiteRT ya transmite texto | API propia con eventos de FSM y persistencia | Comportamiento bajo reconexión, cliente lento y cancelación. |
| ¿Es necesario que cada agente use SLM? | PDF separa agentes de modelos; antecedentes muestran otros diseños | Ingesta y política deterministas; un intérprete | Beneficio de interpretación en tareas reales. |
| ¿YOLO o Gemma para conteo? | Ejemplo específico de detector; objetivo del PDF | YOLO en evaluación principal | Exactitud por región y costo con gente pequeña/oculta. |
| ¿Reducir imagen siempre acelera? | Preprocesamiento visual puede fijar presupuesto | Ensayo 320/480/640 sin prometer mejora | Dimensión interna efectiva del bundle y tiempos calientes. |
| ¿Habilitar thinking? | Existe configuración, pero el autor lo descartó | Siempre desactivado; sin opción en UI/API | Verificar desactivación efectiva. |
| ¿Se ahorra energía al llamar menos? | El protocolo mide ciclo completo; el autor añadirá W periódicos | Separar actividad, potencia observada, energía estimada y contador | Resolución, huecos y diferencias por método. |

## 4. Revisión crítica interna

- Una explicación fluida puede ser falsa; se exige puntuación de contenido y evidencia.
- Un radar válido no describe fuera de cobertura; se exigen regiones comparables.
- El stream puede hacer sentir más rápido el mismo cálculo; se separa percepción e inferencia.
- Menos llamadas no prueba energía menor; se conserva la frontera de medición.
- Conteo con mosaicos puede ser más exacto y mucho más caro; el número de inferencias es visible.
- Un bucle multiagente puede añadir tokens sin aportar decisiones; el MVP usa funciones deterministas.
- El acceso a foto cruda puede explicar diferencias C–D; se separa la variante visual.
- Un sample manual no sustenta precisión, p95 ni superioridad; se propone piloto y ensayo final separados.

No se afirma novedad universal, mejor modelo absoluto, política óptima, ahorro medido ni confiabilidad clínica/ambiental. Son límites del alcance y de la evidencia disponible.

## 5. Reproducibilidad y verificaciones pendientes

Las URLs de documentación y ramas `main` cambian. Antes de implementar o fijar el protocolo, guardar versiones instaladas y los commits usados para cualquier conclusión dependiente de código. No se descargaron ni ejecutaron aquí modelos grandes, servicios de la Pi, cámara o sensores. Los ejemplos internos propuestos no son capturas; los payloads del autor y el análisis de S26 están identificados explícitamente como tales.

No se verificó de forma individual toda la bibliografía de `main.pdf`; no se presenta este documento como un informe de validación de citas. Si se necesita ese trabajo, requiere una pasada específica sobre cada referencia y su afirmación asociada.
