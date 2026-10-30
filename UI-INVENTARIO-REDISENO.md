# Inventario previo al rediseño v2

Este inventario registra la interfaz existente antes de reorganizarla. Los IDs identifican los nodos que coordinan `public/` y los contratos con el backend.

| Área actual | Lecturas, estados y metadatos | Acciones y detalles que deben permanecer |
| --- | --- | --- |
| Navegación y entorno | Cuatro pestañas; conexión SSE; tema; aviso offline y escena simulada. | Preparación, Medición, Experimentación, Replay; selector de escena, avanzar un minuto y reiniciar demo; tema claro/oscuro; contador global de pendientes. |
| Preparación / sistema | CPU %, RAM %, RAM MB (`cpu`, `memory`, `memory-detail`). | Estados de preparación y conexión. |
| Preparación / sensores | SHT40: temperatura y humedad; ENS160: AQI y eCO₂ en resumen; radar: presencia y distancia. Telemetría MQTT completa en `raw`, incluidos campos adicionales como TVOC cuando llegan. | Identidad y estado de cada fuente; JSON crudo copiable. |
| Preparación / modelos | Tres fases separadas (`phases`): YOLO/NCNN, Gemma texto y Gemma imagen, cada una con su estado y detalle. | Sandbox: conversación, texto, enviar, tomar/quitar foto, contar personas, preguntar sobre la foto, progreso y duración de la última tarea. |
| Inicio de medición | Modo A–F y habilitación real; ejecución en curso/reservada; estado y errores. | `measurement-mode`, `measurement-toggle`, confirmación de cierre anticipado, reevaluación Q1–Q7. |
| Sesión y observación | Reloj, duración, progreso, CPU total, RAM sistema, RAM SENSE, temperatura Pi; calidad, pendientes, hora/motivo/campos solicitados, errores. | Completar pendiente, registrar evento real, CSV/ZIP, NDJSON, histórico, formulario con observador, instrumento, W puntual, personas, acción, horas propias de lectura, notas, no observado, motivo, repetir anterior, guardar o dejar pendiente. |
| Lecturas actuales | Radar/presencia con zona B, distancia y fuente Auto/Manual; conteo YOLO; temperatura; humedad; AQI; TVOC; eCO₂ estimado. Por lectura: valor/unidad, edad, región, fuente y estado VALID/UNKNOWN/STALE/CONFLICTING/UNAVAILABLE/ERROR. | Control de presencia Auto/Manual y su valor en B–F; cero distinto de desconocido; ocultación de Q2/YOLO cuando falta `visible_people` humano. |
| FSM, tareas y fallas | WAIT, ACQUIRE, ASSESS, VISION, INTERPRET, REPORT, DEGRADED; transiciones completas, estado actual, última transición, tareas activas/encoladas y degradación. | Grafo o lista de respaldo; en F: suspender/restaurar SHT40, ENS160, radar, cámara; timeout YOLO/Gemma, estado y resumen de fallas. |
| Respuestas e interpretación | Q1–Q7: pregunta, respuesta, estado, fuente, evaluación, limitaciones, faltantes, evidencia y contrato JSON. Hasta diez interpretaciones recientes con validación, origen textual/imagen, fin e historicidad. | Reevaluar una pregunta; abrir evidencia/contrato; historial de ejecuciones y descargas; salud de componentes; diagnóstico con metadatos, transiciones, decisiones, necesidades, errores, recursos y colas. |
| Experimentación | S1–S3, A–F, repetición 1–3; guion completo, reglas y preguntas; Ahora/siguiente paso con tiempo orientativo. | Inicio con condiciones iniciales y reloj al guardar; workspace único compartido; registro de acción real, pendientes y cierre. |
| Replay | ZIP local, ejemplo offline, estado FSM, huecos, hora y cursor; temperatura, humedad, AQI, eCO₂, TVOC, presencia, YOLO, distancia, CPU, RAM sistema, RAM SENSE, temperatura Pi, workers YOLO/Gemma, edad y estado por lectura. | Reproducir/pausar, velocidad, hitos anterior/siguiente, barra y marcadores; filtros y lista completa de eventos; Q1–Q7 guardadas y JSON; tareas, Gemma tardía, observaciones W/personas/acción y horas; muestra/solicitudes originales y JSON de evento. |

Contratos intocables: `api.js`, SSE, endpoints, IDs compartidos, modos A–F, guiones S1–S3, políticas de FSM, almacenamiento y semántica de W. Una respuesta `202` solo acepta la acción; el resultado llega por estado. `record_complete` y `duration_completed` tienen significados distintos.

## Matriz de conservación: elemento anterior → ubicación nueva

| Elemento anterior | Ubicación nueva y acceso | Conservación comprobada |
| --- | --- | --- |
| Pestañas, conexión, tema y demo offline | Barra lateral compacta; conexión y controles de tema/movimiento al pie; demo arriba | IDs originales, cuatro pestañas y escenas intactas; flechas/Home/End navegan pestañas habilitadas. |
| CPU y memoria de preparación | Preparación → Sistema | Valores de CPU %, RAM % y MB siguen en `cpu`, `memory`, `memory-detail`. |
| SHT40, ENS160 y radar | Preparación → Sensores MQTT | Temperatura, humedad, AQI, eCO₂, presencia y distancia visibles; icono propio por sensor. |
| Telemetría MQTT original | Preparación → “Telemetría MQTT · JSON original” | `raw` conserva el JSON completo, incluido TVOC y cualquier campo adicional. |
| YOLO/NCNN, Gemma texto, Gemma imagen | Preparación → Preparación de modelos | Tres estados y detalles separados; iconos v2 `yolo`, `gemma-text`, `gemma-image`. |
| Conversación, foto y tareas manuales | Preparación → Sandbox | Texto, envío, tomar/quitar foto, conteo, pregunta sobre foto, mensajes, carga y tiempo siguen disponibles. |
| Modo A–F, inicio y cierre | Medición → barra de sesión | Selector y acciones originales; cierre anticipado con confirmación; aceptación espera actualización de SENSE. |
| Reloj, progreso y recursos | Medición y Experimentación → panel de tiempo | Duración, CPU, RAM sistema/SENSE y temperatura Pi; icono `timer`. |
| Estado FSM, transición y tareas | Medición y Experimentación → franja de estado | Estado actual, última transición, tareas activas y cola, disparador B y degradación visibles sin abrir el grafo. |
| Grafo FSM completo | Medición y Experimentación → “Inspeccionar máquina de estados” | Siete estados y trece conexiones originales; Cytoscape en la vista conectada; SVG local con arrastre y zoom en offline; pasos en móvil. Cada nodo se inspecciona con clic, teclado o selector: muestra su estado y conexiones sin cambiar la FSM. El icono v2 anima solo el estado en curso y la transición nueva recibe un pulso breve. |
| Radar, YOLO, temperatura, humedad, AQI, TVOC, eCO₂ | Medición y Experimentación → “Lecturas actuales” → Presencia y visión / Ambiente | Valor/unidad, edad y estado visibles; región, fuente y hora bajo “Detalles” de cada tarjeta; distancia y zona B dentro de Radar. |
| Control Auto/Manual de presencia | Tarjeta Radar de Presencia y visión | Modos B–F, zona B, última lectura física y control manual separados. |
| Pendientes y registro humano | Panel de observación y diálogo lateral | Motivo, campos pedidos, W puntual, personas, acción, no observado, repetir, notas, horas de lectura y hora del evento; se conserva Q2 oculto mientras falta conteo humano. |
| Q1–Q7 y reevaluación | Medición y Experimentación → Respuestas actuales y “Reevaluar” | Resumen, respuesta completa, fuente, estado, limitaciones, evidencia JSON y reevaluación bajo las reglas originales. La explicación de actualización queda en “Cómo se actualizan las respuestas”. |
| Interpretaciones, historia, exportación, salud, F y diagnóstico | Medición y Experimentación → secciones desplegables y panel F | Interpretaciones históricas, CSV/ZIP, NDJSON, historial, salud, fallas, timeouts, metadatos, transiciones, decisiones, recursos y colas siguen accesibles. |
| S1–S3, A–F y repetición | Experimentación → selector y “Guion y pasos” | Objetivo, todos los pasos, reglas y preguntas bajo secciones desplegables; “Ahora” y siguiente paso siguen visibles durante la ejecución; mismo workspace compartido. |
| ZIP, ejemplo, controles y eventos de Replay | Replay → encabezado, carga ZIP compacta, reproductor con escala y lista filtrable | Pausa, velocidad, saltos, barra, hitos, filtros, huecos y resultados tardíos; progreso y evento actual sincronizados; controles anterior/siguiente compactos; leyenda creada a partir de las categorías reales de marcadores. Los límites y el resumen del ZIP siguen visibles. |
| 14 métricas y workers de Replay | Replay → Ambiente / Presencia y visión / Recursos / Tareas | Valores, unidades, vigencia y edad conservados; mismas 14 claves de la traza, cada una con su icono v2. Sin celdas visuales vacías. |
| Respuestas, Gemma, observaciones humanas y datos originales de Replay | Replay → respuestas y detalles desplegables | JSON de respuestas, tareas, interpretaciones, W/personas/acción con horas, muestra, solicitudes y evento seleccionado. |

La cuadrícula nueva no introduce celdas de relleno. Ningún ID de contrato ni campo de datos fue eliminado. Las capturas previas facilitadas por el usuario están en `ui-review/before/`.
