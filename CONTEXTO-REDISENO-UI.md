# SENSE — contexto para rediseñar la interfaz

Este documento está pensado para entregarse a Codex antes de rediseñar la página. Describe el proyecto tal como está en el repositorio y distingue los comportamientos que una nueva UI debe conservar. El objetivo del futuro trabajo es mejorar la experiencia visual y operativa durante una medición; crear este documento **no cambia la aplicación**.

## 1. Qué es SENSE

SENSE es un panel local para una Raspberry Pi 5 que observa un aula o zona compartida con sensores ambientales, radar de presencia, cámara con YOLO y un modelo Gemma. Compara seis modos de adquisición e interpretación (A–F), registra ejecuciones de hasta 30 minutos y permite añadir observaciones humanas externas. Hay una versión `/offline` para desarrollar la interfaz sin hardware ni modelos y un visor Replay para estudiar ZIP exportados.

El producto tiene dos públicos en la misma página: la persona que opera/observa la ejecución en vivo y la persona que luego analiza la traza. En el rediseño, la primera debe entender de un vistazo **qué está ocurriendo, qué debe hacer ahora, qué datos son vigentes y qué falta registrar**. El detalle técnico debe seguir accesible para análisis.

## 2. Mapa del repositorio

| Archivo o módulo | Responsabilidad |
| --- | --- |
| `main.py` | Aplicación Flask; MQTT; preparación de YOLO/Gemma; cámara; endpoints; flujo SSE `/events`. |
| `sense/pilot.yaml`, `sense/config.py` | Parámetros del piloto y validación; modos habilitados, TTL, plazos y presupuestos. |
| `sense/acquisition.py`, `sense/context.py`, `sense/contracts.py` | Adaptación de telemetría, evidencia con fuente/hora/región/vigencia, snapshots y contratos. |
| `sense/policy.py`, `sense/orchestrator.py` | Preguntas Q1–Q7, decisiones A–F y máquina de estados; autoridad para activar inferencias. |
| `sense/agents.py`, `sense/inference.py`, `sense/runtime.py` | YOLO, Gemma, validación y trabajadores/colas asíncronas. |
| `sense/service.py`, `sense/health.py`, `sense/faults.py`, `sense/telemetry.py` | Coordinación, publicación del estado, salud, fallas de F y recursos de la Pi. |
| `sense/protocol.py`, `sense/storage.py`, `sense/trace.py` | Protocolo del observador, SQLite, muestras por segundo y exportaciones. |
| `public/index.html` | Estructura de todas las secciones, diálogo del observador y carga de scripts. |
| `public/panel.css`, `public/measurement.css`, `public/replay.css` | Tema/base, medición/experimentación y Replay. |
| `public/theme.js`, `public/api.js`, `public/app.js` | Tema claro/oscuro, transporte real/simulado y presentación general. |
| `public/measurement.js`, `public/experiment.js` | Vista de ejecución, respuestas, salud, controles y protocolo guiado/observador. |
| `public/offline.js` | Backend simulado en memoria para la misma UI de `/offline`. |
| `public/replay-data.js`, `public/replay.js` | Lectura/validación de ZIP y reproducción temporal. |
| `serve_offline.py` | Servidor local de la UI sin importar `main.py` ni iniciar hardware. |
| `tests/` | Pruebas de backend y pruebas DOM/frontend con Node. |
| `README.md` | Comportamiento del piloto, protocolo experimental y uso actual. |

El frontend es HTML/CSS/JavaScript sin framework. No hay build de frontend. Las páginas `/` y `/offline` usan `public/index.html`; `api.js` elige entre `fetch`/`EventSource` reales y el simulador de `offline.js`.

## 3. Arquitectura y límites de responsabilidad

```text
Sensores/Rust → MQTT → Flask → ExperimentService → SenseOrchestrator
                                      │                    ├─ contexto y política
                                      │                    ├─ YOLO / Gemma
                                      │                    └─ SQLite / muestras / eventos
                                      └─ /events cada ~1 s → frontend compartido

/offline → transporte simulado en memoria → mismo frontend
ZIP exportado → Replay local en el navegador, sin backend de inferencia
```

El navegador **presenta** el estado y envía acciones explícitas. No decide cuándo ejecutar YOLO/Gemma, no calcula respuestas Q1–Q7, no modifica la FSM y no controla el cierre automático. El backend continúa durante una desconexión o al cerrar la pestaña. Las inferencias tardías se registran como históricas y no se convierten en respuestas actuales.

La telemetría MQTT llega del servicio Rust existente. La app se apoya en Flask, SQLite, YOLO/NCNN y Gemma por LiteRT-LM. En hardware real también dependen del sistema de la Raspberry la cámara, sensores y broker. El rediseño de frontend debe poder probarse sin todo ello en `/offline`.

## 4. Secciones actuales y navegación

`public/index.html` contiene cuatro pestañas:

1. **Preparación**: estado CPU/memoria, sensores MQTT, preparación de modelos, sandbox de foto/YOLO/Gemma y telemetría cruda.
2. **Medición y pruebas**: ejecución A–F sin protocolo guiado, con el espacio de trabajo de medición.
3. **Experimentación**: escenario S1–S3, modo A–F y repetición 1–3; inicia una ejecución guiada con observaciones humanas. Reutiliza el mismo nodo `#measurement-workspace`, que `experiment.js` mueve dentro de esta sección al ejecutar.
4. **Replay**: importa un ZIP y reproduce la traza sin ejecutar sensores ni inferencias.

Medición y Experimentación se habilitan cuando terminan las fases de preparación, aunque una fase fallida puede permitir monitoreo degradado. Una ejecución guiada puede continuar si se navega a otra pestaña; el contador global de pendientes permanece disponible. Al terminar, el espacio de trabajo puede volver a Medición y pruebas. El tema claro/oscuro sigue la preferencia del sistema hasta que la persona elige uno manualmente; esa elección se guarda en `localStorage`.

En escritorio la medición usa contenido principal y una barra lateral fija con tiempo, progreso, recursos, pendientes y descargas. En móvil esa barra se convierte en una franja superior fija y el grafo se sustituye por pasos. La vista usa actualmente una paleta verde sobria con estados azul/verde/rojo y tarjetas de fondo claro u oscuro. Cytoscape crea el grafo interactivo solo si carga la librería externa y la pantalla no es pequeña; siempre existe la lista HTML de respaldo.

## 5. Modos, estados y preguntas

| Modo | Comportamiento de adquisición/interpretación |
| --- | --- |
| A | YOLO periódico, inicialmente cada 30 s. |
| B | YOLO por entrada/salida confirmada de la zona próxima del radar, con histéresis, confirmación y cooldown. |
| C | YOLO por necesidad de evidencia visual; respuestas por reglas. |
| D | Como C, con Gemma textual solo ante una necesidad adicional legítima. |
| E | Como D, con imagen pertinente y Gemma multimodal para Q7 cuando corresponde. |
| F | Política de E con controles de fallas simuladas por software y sus registros. |

FSM real: `WAIT → ACQUIRE → ASSESS`, con ramas `VISION`, `INTERPRET`, `REPORT` y `DEGRADED`. El ciclo vuelve a `WAIT`. `DEGRADED` significa que continúa con evidencia parcial; no significa que toda la ejecución haya acabado. El grafo muestra estados y transiciones, pero las tareas de Gemma pueden seguir asíncronamente cuando la FSM ya volvió a `WAIT`.

Preguntas: Q1 presencia, Q2 conteo visible, Q3 ambiente, Q4 cambios ambientales, Q5 suficiencia/consistencia, Q6 relación contextual y Q7 información adicional de imagen (solo E/F). Q1–Q5 son reglas; Q6 puede recibir interpretación textual y Q7 multimodal. Una respuesta puede estar `RESOLVED`, `PARTIAL`, `ABSTAINED`, `PENDING`, `INTERPRETED` o `NOT_APPLICABLE`. La UI debe distinguir resultado, limitaciones, fuente y momento de evaluación. **Reevaluar** es opcional: no obliga a capturar imagen ni a llamar Gemma.

Las observaciones tienen valor, fuente, región, hora, edad y estado (`VALID`, `UNKNOWN`, `STALE`, `CONFLICTING`, `UNAVAILABLE`, `ERROR`). Cero personas es un valor válido; `null`/desconocido no significa cero. El conteo YOLO es estimación, la presencia del radar tiene cobertura limitada, eCO₂ es estimado y la coincidencia entre ocupación y ambiente no demuestra causalidad. La vigencia inicial configurada es 6 s para radar, 10 s para ambiente y 60 s para conteo visual. No presentar una lectura vencida como actual.

En B hay que diferenciar **presencia detectada** de **dentro/fuera de zona próxima**. El control Auto/Manual de B–F es una intervención del operador, no una lectura real del radar ni ground truth. En F se pueden suspender/restaurar entradas de SHT40, ENS160, radar y cámara, y armar timeouts para la siguiente tarea legítima; una falla simulada no es un corte eléctrico. Restablecer entrada no implica recuperación comprobada hasta recibir evidencia nueva.

## 6. Flujo de experimentación guiada

La ejecución guiada dura como máximo 1800 s y combina `escenario × modo × repetición`: S1–S3, A–F y repeticiones 1–3. Antes del inicio se eligen los tres parámetros y se abre el formulario de condiciones iniciales: observador, identificación del vatímetro, potencia W y personas observadas. El reloj comienza **al guardar** esos datos. No se debe mostrar una sesión anticipadamente como activa.

Guiones existentes:

| Escenario | Acciones orientativas | Puntos de control especiales |
| --- | --- | --- |
| S1, estabilidad | 0–10 min aula vacía; 10–15 entra una persona; 15–30 permanece sentada. | 10 y 15 min. |
| S2, ocupación | 0–5 vacía; 5–10 entra una; 10–15 entran dos; 15–20 permanecen tres; 20–25 salen dos; 25–30 sale la última. | 5, 10, 15, 20 y 25 min. |
| S3, ambiente | 0–10 dos personas y condición inicial; 10–20 cambio seguro de ventilación; 20–30 condición inicial restaurada. | 10 y 20 min. |

Los tiempos del guion son orientativos; el observador registra cuándo ocurrió una acción real. B exige pasar a menos de 30 cm del radar para probar la política; D necesita cambios ambientales suficientes para solicitar Gemma textual. La ausencia de activación también es un resultado experimental válido.

Durante la sesión, el backend crea solicitudes de observación: potencia W cada 60 s, puntos del guion, inicio/fin/falla de tareas, cambios confirmados y cierre. Cada solicitud enumera sus campos (`power_w`, `visible_people`, `action`); el formulario muestra solo los necesarios. Se puede registrar además un evento real no previsto. El backend detiene la ejecución a los 30 min aunque el navegador se cierre, solicita un registro final y mantiene pendientes hasta resolverlos. Finalizar antes de tiempo conserva la duración real y no cuenta como una sesión completa de 30 min.

Al responder una solicitud, la hora del evento proviene del backend y no cambia al abrir el formulario. La persona puede indicar horas de lectura W/personas, notas, declarar un dato **no observado** con motivo o pulsar **Repetir anterior** para confirmar explícitamente un valor anterior, incluido cero. **Dejar pendiente** no detiene el backend. Los pendientes sobreviven a recargas; el borrador sin guardar solo permanece en memoria de la pestaña actual. Una observación humana posterior no se debe hacer pasar por evidencia de una foto anterior.

**Invariante científica importante:** cuando una ejecución guiada tiene pendiente una observación humana de `visible_people`, la UI actual oculta la estimación YOLO Q2 hasta recibirla. El rediseño debe conservar este cegamiento para no influir en el observador. Las observaciones humanas se almacenan separadas y no alimentan la política de inferencia. W es potencia puntual del conjunto declarado de equipos; no calcular Wh ni atribuirla solo a Gemma.

## 7. Qué ofrece hoy la vista de medición

`#measurement-workspace` contiene:

- Introducción, selector A–F, botón Comenzar/Finalizar y estado de la ejecución.
- Reloj transcurrido/duración, barra de progreso, CPU total, RAM sistema, RAM SENSE y temperatura de la Pi.
- Pendientes del observador, botón para completarlos y botón de evento real; cobertura y descargas plegadas.
- FSM/grafo interactivo o lista de siete pasos; última transición, tareas en segundo plano y avisos de degradación.
- Lecturas de radar, YOLO y ambiente en un `<details>`; cada lectura muestra valor, edad, región y estado.
- En F, controles de fallas, timeout, estado y resumen de fallas.
- Tarjetas Q1–Q7 con respuesta, estado, fuente, hora, limitaciones, faltantes y contrato técnico plegado.
- Interpretaciones recientes de Gemma (hasta 10), con origen histórico y detalle completo plegado.
- Historial, exportaciones, salud de componentes y diagnóstico técnico plegados.

La interfaz se actualiza con la publicación SSE aproximadamente cada segundo. Los resultados, estados y tareas pueden llegar en distinto orden. Una respuesta reciente no vuelve actual una interpretación histórica. El documento puede perder conexión: en ese caso debe explicar que muestra la última información recibida y bloquear nuevas acciones hasta reconectar.

### Hallazgos de UX para orientar el rediseño

1. El guion de Experimentación se pliega al iniciar y no destaca el tramo vigente ni el siguiente paso. El operador debe recordar tiempos y acciones mientras observa el sistema.
2. Las solicitudes nuevas pueden abrir automáticamente un diálogo. En una sesión con W cada minuto y eventos adicionales, eso interrumpe la observación del aula; existe contador de pendientes, pero no una cola contextual visible con motivo, hora y campos de cada solicitud.
3. El grafo técnico domina la primera sección. Las lecturas que se necesitan para medir quedan plegadas debajo; en móvil se suma una franja fija con cuatro métricas de recursos.
4. Estado, progreso, acciones del observador y calidad de registro están dispersos. Para decidir qué hacer ahora se debe recorrer varias zonas.
5. `Finalizar` envía el cierre inmediatamente. En una sesión larga conviene una confirmación clara antes de terminar anticipadamente.
6. Medición y Experimentación reutilizan físicamente el mismo workspace, pero se perciben como dos destinos distintos; la navegación y el estado activo pueden aclararse.
7. Las pestañas actuales son botones con `aria-selected`; una implementación semántica de pestañas, navegación por teclado y enlace para saltar al contenido mejorarían la accesibilidad.

Estos son puntos de diseño, no autorización para cambiar las reglas de la medición. Ya existen decisiones buenas que deben preservarse: visualización de vigencia y fuente, cero distinto de desconocido, estado degradado, datos históricos diferenciados, modo oscuro, controles táctiles y formulario que pide únicamente los campos solicitados.

## 8. Datos y API disponibles para la nueva UI

`GET /events` emite un snapshot JSON por SSE, aproximadamente cada segundo. En él, `measurement` ofrece, entre otros:

```text
running, reserved, run, elapsed_s, fsm, cycle.actions, transitions,
context.observations, answers, needs, tasks.active, tasks.queued,
interpretations, decisions, errors, resources, component_health,
reactive_trigger, presence_control, fault_control,
observer_requests, observer_previous, quality, enabled_modes
```

`run` contiene ID, modo, política efectiva, escenario, repetición, `guided`, inicio/fin, estado, duración y motivo de cierre. `observer_requests` contiene `request_id`, `requested_at`, `reason`, `fields` y estado. `quality` contiene muestras, segundos sin muestra, observaciones pendientes/no disponibles, fallas/timeouts, muestras incompletas, `duration_completed` y `record_complete`. **`record_complete` significa que el registro esperado está cubierto; `duration_completed` indica específicamente que se cumplieron los 30 minutos.**

Endpoints que usa el frontend:

| Acción | Endpoint |
| --- | --- |
| Iniciar prueba o sesión guiada | `POST /api/experiments/start` |
| Finalizar antes de tiempo | `POST /api/experiments/stop` |
| Reevaluar Q1–Q7 | `POST /api/experiments/query` |
| Intervenir presencia Auto/Manual | `POST /api/experiments/presence` |
| Inyectar/restaurar fallas F | `POST /api/experiments/faults` |
| Historial y detalle de una sesión | `GET /api/experiments`, `GET /api/experiments/<run_id>` |
| Crear evento real / responder pendiente | `POST /api/experiments/<run_id>/observer-requests`, `POST /api/experiments/<run_id>/observer-requests/<request_id>` |
| Exportar | `GET /api/experiments/<run_id>/export` (`?format=csv` para ZIP) |

Los comandos suelen devolver `202` y el estado definitivo llega luego por SSE. No asumir que el clic ya produjo una inferencia o que una acción aceptada terminó. `api.js` centraliza transporte y enlaces de exportación; el rediseño debe seguir usando ese adaptador para que funcione en `/` y `/offline`.

## 9. Replay, registros y simulación

SQLite guarda ejecuciones, eventos, observaciones humanas, solicitudes y muestras de hasta una por segundo. El ZIP CSV incluye metadatos, muestras, eventos, observaciones, tareas, respuestas, lecturas W, solicitudes, fallas y referencias de imagen. NDJSON conserva el registro original. Las fotografías no se guardan. Una exportación durante una ejecución es parcial; puede repetirse al terminar y resolver pendientes.

Replay importa el ZIP **localmente**; no envía el archivo al servidor ni vuelve a correr políticas/modelos. Tiene reproducción/pausa, velocidad, salto entre hitos, cursor, filtros de eventos y paneles de lecturas, respuestas, tareas, interpretaciones, observaciones humanas y JSON original. Debe preservar huecos de muestras, edad de evidencia y resultados tardíos. `/offline` ofrece un ZIP de ejemplo de 30 minutos y escenas para preparación, ejecución, pendientes, cierre, falla F y datos incompletos.

Para revisar cambios de UI sin hardware:

```sh
python3 serve_offline.py
# http://127.0.0.1:8000/offline
```

La URL real usa `python main.py` y depende de MQTT, cámara, modelos y el runtime Gemma. Para un rediseño visual, empezar por `/offline` evita atribuir errores de hardware a la UI. Los datos de `/offline` son simulados y deben permanecer claramente identificados como tales.

## 10. Alcance recomendado del futuro rediseño

La dirección visual concreta queda abierta: se puede proponer una nueva jerarquía, tipografía, color, composición y microinteracciones. Priorizar primero el trabajo del observador durante los 30 minutos:

1. Resumen persistente y compacto: escenario/modo/repetición, tiempo transcurrido/restante, conexión, fase de la ejecución y pendientes.
2. Bloque **Ahora / siguiente paso** calculado a partir del escenario y `elapsed_s`, dejando claro que el tiempo orienta y la acción real se registra cuando ocurre.
3. Lecturas operativas visibles con estado, antigüedad y fuente; mostrar el grafo/FSM y el diagnóstico como inspección secundaria.
4. Cola de solicitudes con motivo, hora del evento, campos pedidos y acción de responder; conservar el formulario, sus validaciones, la opción de no observado y el cegamiento de Q2.
5. Señales claras de calidad: datos vencidos, faltantes, muestra interrumpida, fallo, sesión finalizada anticipadamente y registro todavía incompleto.
6. Confirmación de finalización anticipada y mensajes de error que expliquen el siguiente paso.
7. Diseño responsive, tema claro/oscuro, contraste y navegación completa por teclado.

El futuro cambio puede modificar `public/index.html`, CSS y JS de presentación, y adaptar pruebas frontend. Debe mantener los IDs/contratos necesarios o actualizar de forma coordinada sus usos. No duplicar `#measurement-workspace` ni IDs. No cambiar la política de A–F, el protocolo, la base de datos, los endpoints ni la semántica de las medidas solo para acomodar una maqueta. Si una idea requiere datos que el SSE no entrega, identificarlo antes de inventarlos en el navegador.

## 11. Criterios para revisar el resultado futuro

- Se puede iniciar una prueba A–F y una sesión guiada S1–S3 desde la UI nueva.
- Durante la sesión se entienden el paso del guion, el tiempo, la FSM, las tareas asíncronas y qué observaciones están pendientes.
- Se distinguen datos actuales, vencidos, desconocidos, manuales, simulados e históricos; `0` sigue siendo un dato válido.
- Q2 de YOLO permanece oculto cuando corresponde solicitar primero el conteo humano.
- W sigue siendo una lectura puntual, sin energía calculada ni atribución automática al modelo.
- Dejar pendiente, repetir anterior, no observado, registrar evento real y completar registros históricos siguen funcionando.
- F solo muestra controles de fallas cuando está activo y no promete que una falla sea física.
- Exportaciones, Replay y la página `/offline` siguen funcionando.
- En móvil se puede leer y registrar una medición sin que una franja fija tape contenido o controles.
- Ejecutar, según corresponda, `.venv/bin/python -m unittest discover -s tests -v` y `node --test tests/*.test.cjs`; revisar visualmente `/offline` en escritorio y móvil. Las pruebas DOM existentes no sustituyen la revisión visual.

## 12. Encargo listo para pegar en Codex

> Lee primero `CONTEXTO-REDISENO-UI.md` y el código actual de `public/`. Quiero un rediseño general de la interfaz SENSE, centrado en que una persona pueda operar una medición de 30 minutos y entender qué ocurre sin buscar información en varias secciones. Propón una jerarquía visual clara para el paso actual del escenario, lecturas vigentes, observaciones pendientes, respuestas y estado de la FSM. Mantén Preparación, Medición, Experimentación, Replay, los temas claro/oscuro y la experiencia móvil. Usa `/offline` para revisar el flujo sin hardware. Conserva los contratos del backend, la separación entre observación humana e inferencia y el cegamiento de Q2 descritos en este documento. Antes de implementar, muéstrame una propuesta de estructura visual y las decisiones principales; después aplica el rediseño al frontend y verifica pruebas y vistas en escritorio/móvil.

