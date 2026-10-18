# 08. Plan de implementación por incrementos

Este documento conserva el plan por incrementos. Tras la autorización posterior del autor se escribió una primera implementación independiente en Python; estado efectivo, archivos y límites en [16](16-version-python.md). No se modificaron la aplicación Rust, el broker ni la Raspberry. La versión ampliada se prepara para trasladarla a la Pi sin ejecutarla aquí.

## 1. Estructura inicial sugerida

Dentro de `python_prueba/`, cuando se autorice implementar:

```text
app.py          API y ciclo de vida
context.py      validación interna, snapshots y frescura
orchestrator.py FSM, política y presupuestos
mqtt_ingest.py  adaptación del topic existente
vision.py       cámara, detector y perfiles visuales
slm.py          cliente LiteRT-LM y validación de respuesta
store.py        persistencia de sesiones y eventos
experiment.py   controles de fallos, muestras de recursos, potencia y CSV
tests/          casos de política, contratos e integración simulada
docs/           esta investigación
```

Es un mapa de responsabilidades, no obligación de crear archivos vacíos ni interfaces con una sola implementación. Empezar con menos archivos si el flujo aún es pequeño y separar cuando el código lo requiera. Mantener una sola definición de las reglas de vigencia y admisión; no duplicarlas en frontend, prompts y endpoints.

No depender del proyecto Rust ni proponer su refactor. No añadir fine-tuning, RAG, memoria vectorial, frameworks multiagente, reconocimiento facial o control de actuadores al MVP.

## 2. Incrementos y criterios de salida

| Paso | Construir / investigar | Prueba mínima | Criterio para continuar |
|---|---|---|---|
| 0. Contratos reales | Capturar MQTT y versiones del entorno; revisar cámara y modelo | Payloads completos y descripción del bundle, sin secretos | Q01–Q04 resueltas o límites explícitos. |
| 1. Contexto sin modelos | Suscripción única, normalización, snapshots e historial | Validez parcial, stale sin mensajes, duplicado y región no comparable | Ningún dato faltante se convierte en cero. |
| 2. FSM con reglas | WAIT–ACQUIRE–ASSESS–REPORT y degradación | Tabla de transiciones con reloj simulado | Resultados reproducibles sobre una secuencia fija. |
| 3. Registro y API | Sesiones, eventos persistidos, SSE, cancelación | Reconexión, idempotencia, cliente lento, reinicio | El frontend observa decisiones y puede desconectarse sin perder trazabilidad. |
| 3b. Controles y mediciones | Fallos por fuente, muestreo de recursos, W manuales y CSV | Desactivar una fuente compartida, resultado tardío, restauración, huecos de potencia y export consistente | Intervenciones y datos exportados trazables a eventos y tiempos. |
| 4. Cámara y YOLO | Un dueño de cámara, conteo global, contrato con tiempos | Imagen conocida, fallo, conteo cero, correspondencia píxeles/metadata | Calidad/costo medidos en Pi; export e inferencia compatibles. |
| 5. Política adaptativa | Necesidades, TTL, cooldown y presupuesto pesado | Presencia sin visión; conteo con una visión; error sin bucle | Cada activación tiene razón y presupuesto. |
| 6. Gemma estructurado | Interpretación de snapshots y fallback | Límite real de salida, schema/IDs, timeout, contradicción numérica | C–D evaluables con evidencia idéntica. |
| 7. Ruta visual adicional | Imagen a Gemma solo si es necesaria para el alcance elegido | Mismas imágenes 320/480/640; frío y caliente | Decidir si E_visual vale su costo y actualizar alcance. |
| 8. Frontend de pruebas | FSM en vivo, decisiones, toggles de fuentes, gráficos, entrada W y exportación CSV/ZIP | Misma sesión observada por dos clientes; orden de intervención confirmado por servidor | UI no cambia reglas ni fabrica métricas; fallos y lecturas quedan registrados. |
| 9. Piloto y congelamiento | Elegir perfiles/umbrales y protocolo | Sesiones repetidas, datos fuera de prueba final | Manifiesto y rúbrica aprobados antes de evaluar. |

No se debe bloquear el diseño por detalles del frontend. Los pasos 1–7 se pueden validar con clientes HTTP y registros. La UI se construye sobre contratos ya comprobados.

## 3. Decisiones iniciales recomendadas

| Decisión | Propuesta | Qué obligaría a revisarla |
|---|---|---|
| Control | FSM determinista con `Enum` y funciones | Crecimiento real de jerarquías/transiciones difíciles de auditar. |
| Modelo | Una instancia residente de Gemma 4 E2B | Piloto muestra costo injustificado o calidad insuficiente. |
| Thinking | Siempre desactivado y fuera del experimento | Solo una nueva instrucción explícita del autor; no hay opción de activación en API/UI. |
| Visión de conteo | YOLO26n NCNN en CPU, primero una pasada | Calidad insuficiente por objetos pequeños; evaluar 640/mosaicos. |
| Imagen semántica | 480 en lado mayor como candidato de envío | Medición muestra que 320 basta o se necesitan detalles mayores. |
| Recursos | Una acción pesada simultánea | Ensayo de concurrencia demuestra mejora sin pérdidas de ingesta ni calidad. |
| Registro | SQLite local y artefactos por ID | Volumen/concurrencia medidos exceden lo que resuelve. |
| Streaming | HTTP + SSE | Necesidad real de audio o control bidireccional continuo. |
| Recursos | Muestreo automático nominal cada 1 s | Ajustar en piloto si el costo de medir altera el sistema. |
| Potencia | W manuales nominalmente cada 30 s | Cadencia/resolución del medidor o carga humana exigen otro intervalo. |
| Framework de agentes | Ninguno | Solo si resuelve una necesidad concreta mejor que el código actual. |

No confundir estas decisiones con valores finales: TTL, ventanas, tiempos globales, cooldown, conf/IoU y cadencias se fijan con piloto. La propuesta de repeticiones de [11](11-escenarios-y-repeticiones.md) se revisa antes de la prueba final según variabilidad y precisión, sin elegir el tamaño después de observar si un resultado es favorable.

## 4. Checklist de capacidades en la Raspberry

Lecturas futuras recomendadas, sin ejecutar nada remotamente en esta entrega:

```bash
uvx litert-lm --version
uvx litert-lm serve --help
uvx litert-lm describe gemma4-e2b
python3 --version
python3 -c 'import picamera2; print(picamera2.__file__)'
python3 -c 'import ultralytics; print(ultralytics.__version__)'
```

Obtener también SO/kernel, memoria/swap, versiones de NCNN/OpenCV y metadata del modelo exportado. No ejecutar exportaciones ni descargas durante la ventana de medición.

Para el topic existente, una muestra diagnóstica posible es:

```bash
mosquitto_sub -h 127.0.0.1 -t 'rustio/rpi5-01/telemetry' -C 5
```

La captura debe complementarse con conocimiento del productor para interpretar timestamps, unidades, arranque y calidad. No modificar su frecuencia o QoS como efecto secundario de consumirlo.

## 5. Riesgos y señales de detección temprana

| Riesgo | Señal | Mitigación mínima |
|---|---|---|
| SLM no mejora reglas | Más explicaciones, mismos aciertos o más afirmaciones falsas | Mantener baseline; informar H3 sin apoyo si ocurre. |
| Modelo ignora límite/configuración | Salidas más largas o hilos efectivos distintos | Prueba de capacidades y versión fijada. |
| Saturación de CPU | MQTT pierde eventos mientras infiere | Aislar trabajo bloqueante y una acción pesada; medir cola. |
| Foto ya vieja al responder | TTL menor que captura+inferencia | Semántica histórica explícita; no prometer ocupación actual. |
| Comparación injusta | D usa imagen que C no vio | Separar E_visual o congelar evidencia equivalente. |
| Conteo lento | Muchos mosaicos y precalentamiento repetido | Medir fases antes de aumentar tamaño o paralelismo. |
| Cancelación aparente | UI dice cancelado pero CPU sigue ocupada | Acuse real del worker; no liberar slot anticipadamente. |
| Energía no distinguible | Diferencias menores que pasos del contador | Ensayos adecuados o instrumento distinto; resultado no evaluable. |
| Dependencia de paquete del sistema | Picamera2 no importa en uv | Python compatible o worker dedicado de cámara. |

## 6. Definición de prototipo terminado

Una consulta de presencia se resuelve por MQTT sin modelos. Una consulta de conteo activa YOLO una vez y registra captura/ROI/calidad. Una interpretación recibe un snapshot congelado con thinking desactivado. La web ve decisiones y motivos mediante SSE, desactiva/restaura fuentes por una capa de prueba y registra W manuales. Recursos, intervenciones, observaciones, respuestas y métricas se exportan en CSV vinculados por IDs. Las cancelaciones y reconexiones son auditables, y A–D comparten guion y configuración base.

Cumplir eso permite empezar un piloto útil. No equivale a validar hipótesis ni a terminar la evaluación de tesis.
