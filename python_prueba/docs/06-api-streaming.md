# 06. API de experimentos y streaming

Estado posterior: se escribió la API de primera versión; contrato ejecutable y ejemplos actualizados en [README de Python](../README.md), alcance y verificación pendiente en [16](16-version-python.md). Los ejemplos de diseño de este documento no reemplazan ese contrato.

## 1. Recomendación

Sí conviene una API streaming. Su función es hacer observable el ciclo completo: espera, selección de evidencia, captura, detector, SLM, validación y salida. No basta retransmitir tokens de Gemma. La inferencia no se acelera por transmitirla; mejora el feedback y permite separar tiempos.

Propuesta de despliegue: API de orquestación en puerto 8000, LiteRT-LM en loopback 8080 y Mosquitto local. El navegador se comunica solo con la API. Así una llamada directa al modelo no se salta la política, las colas o el registro. Durante desarrollo se pueden conservar los puertos existentes; no son requisitos del protocolo.

## 2. Endpoints mínimos propuestos

| Método y ruta | Función |
|---|---|
| `POST /v1/runs` | Crear sesión y encolar trabajo; respuesta 202 con ID, configuración y URLs. |
| `GET /v1/runs/{id}` | Estado, manifest, resultado parcial/final y métricas disponibles. |
| `GET /v1/runs/{id}/events` | Eventos SSE, con cursor de reconexión. |
| `POST /v1/runs/{id}/cancel` | Solicitar cancelación idempotente. |
| `GET /v1/runs/{id}/sources` | Disponibilidad física conocida y disponibilidad efectiva para la política. |
| `POST /v1/runs/{id}/faults` | Aplicar o programar un fallo lógico de prueba sobre una fuente. |
| `POST /v1/runs/{id}/faults/{fault_id}/clear` | Retirar un fallo de forma idempotente; no fabricar una lectura al restaurar. |
| `POST /v1/runs/{id}/power-readings` | Registrar lectura manual W o contador Wh/kWh, con instante observado. |
| `POST /v1/runs/{id}/annotations` | Anotar inicio de escenario o evento humano de referencia. |
| `GET /v1/runs/{id}/exports/{table}.csv` | Descargar una tabla experimental con esquema estable. |
| `GET /v1/runs/{id}/export.zip` | Paquete de CSV, manifiesto, diccionario y eventos originales. |
| `GET /v1/context` | Snapshot actual de solo lectura, con tiempo y calidad. |
| `POST /v1/artifacts` | Cargar una imagen de prueba con límites y validación. |
| `GET /health` | Diagnóstico pasivo, resultado previo de cámara/modelos, sensores recientes y `can_start_session`; sin sondear/inferir. |
| `POST /v1/runtime/prepare` | Comprobación completa en segundo plano: Gemma, NCNN, calentamiento habilitado, captura/conteo reales y lecturas nuevas de sensores; cuerpo `{}`, respuesta 202 y progreso en `/health`. |

La exportación CSV y los controles de experimentación son requisitos explícitos del autor. [10 — controles y CSV](10-controles-y-csv.md) fija sus contratos y [11 — escenarios y repeticiones](11-escenarios-y-repeticiones.md) define cómo utilizarlos de forma comparable. Estos endpoints son diseño pendiente de implementación.

Ejemplo de creación, ilustrativo:

```json
{
  "variant": "D",
  "source_mode": "live",
  "question": {
    "type": "explain_context",
    "scope_id": "camera-radar-overlap-1"
  },
  "duration_s": 600,
  "profile_id": "pilot-v1"
}
```

`duration_s=600` es ejemplo de contrato, no duración suficiente para demostrar energía. El servidor valida el perfil y límites; el cliente no envía comandos shell, nombres de funciones arbitrarios ni configuración privada de LiteRT-LM. Para ensayo manual de imagen, la pregunta referencia un `artifact_id` ya cargado. La captura en vivo y la carga de imagen son orígenes diferentes y deben figurar en el manifiesto.

El perfil puede incluir `fault_plan_id` y `resource_sample_period_s`. El plan queda congelado al admitir la sesión; las intervenciones manuales posteriores se agregan como eventos y marcan la ejecución como exploratoria si se apartan del plan final. No permiten editar retrospectivamente el tratamiento. Thinking es siempre falso y no es un parámetro público.

La petición puede incluir una clave de idempotencia: mismo cliente + clave + cuerpo devuelve la misma sesión; reutilizar la clave con otro cuerpo devuelve conflicto. Es necesaria para que un retry del frontend no duplique ensayos o capturas.

## 3. Qué transmite SSE

Formato de ejemplo:

```text
id: run-001:17
event: action.started
data: {"schema_version":1,"run_id":"run-001","episode_id":"ep-003","action_id":"a-002","sequence":17,"occurred_at":"2026-10-17T18:00:00Z","monotonic_ns":1250000000,"payload":{"tool":"count_people","reason":"count_missing"}}

```

Tipos propuestos:

| Evento | Contenido útil |
|---|---|
| `run.accepted`, `run.started` | Admisión, espera y configuración fijada. |
| `observation.accepted`, `observation.rejected` | Referencias y motivo; no payloads enormes. |
| `context.updated` | Snapshot nuevo y dimensiones que cambiaron. |
| `state.changed` | Estado anterior, destino, guarda y snapshot. |
| `action.started`, `action.completed`, `action.failed` | Herramienta, evidencia, duración, estado y error tipado. |
| `model.delta` | Texto provisional, no validado. |
| `answer.validated`, `answer.rejected` | Resultado aceptado o causa de descarte. |
| `source.availability_changed` | Fuente, disponibilidad efectiva, motivo y versión del cambio. |
| `fault.scheduled`, `fault.applied`, `fault.cleared` | Intervención solicitada y momento real de efecto. |
| `resource.sample` | Muestra periódica de CPU, memoria, temperatura y colas. |
| `power.reading_recorded` | Lectura manual, hora observada y hora de introducción. |
| `annotation.recorded` | Escenario/evento de referencia; con canal y permisos separados de la política. |
| `protocol.step_due` | Indicación del guion al investigador; no prueba que la acción física ya ocurrió. |
| `followup.scheduled`, `followup.completed`, `followup.expired` | Comprobación, evidencia asociada, plazo y vínculo entre episodios. |
| `run.cancel_requested` | Cancelación recibida; no significa cómputo ya detenido. |
| `run.completed`, `run.cancelled`, `run.failed` | Un único cierre lógico con resultado y métricas. |

`REPORT` corresponde a cierre del episodio. Una sesión continua puede emitir varios resultados de episodio antes de terminar. El stream diferencia ambos niveles con sus IDs.

Una salida incluye `followup_status` y `next_check_at` si necesita corroboración. La siguiente evaluación es otro episodio enlazado con `followup_of_episode_id`; no se confunde sesión terminada con situación resuelta. La interfaz distingue instrucción programada, acción real anotada y decisión del sistema. El guion futuro y las etiquetas humanas nunca se incluyen en el prompt para anticipar respuestas.

## 4. Semántica de entrega

SSE define eventos, IDs y reconexión mediante `Last-Event-ID`; no garantiza persistencia por sí mismo [S11]. Propuesta de SENSE:

1. Persistir el evento con secuencia única por sesión antes de ofrecerlo al stream.
2. Al reconectar, reenviar los posteriores al cursor. El frontend deduplica por ID; no afirmar entrega exactamente una vez.
3. Capturar un límite de secuencia al pasar de replay a seguimiento para evitar huecos entre ambos.
4. Si el cursor ya fue eliminado por retención, devolver un error explícito antes de abrir SSE y ofrecer snapshot/resultado; no simular historial completo.
5. Emitir comentarios heartbeat sin convertirlos en mediciones ni transiciones. El proxy no debe acumular toda la respuesta antes de entregarla.
6. Al recibir un terminal, el frontend cierra `EventSource`; al reconectar a una sesión ya cerrada, el servidor permite recuperar su final y no recalcula nada.

No mantener una cola ilimitada por navegador. Un cliente lento puede desconectarse y recuperar eventos desde el almacenamiento; jamás bloquear captura o ingesta esperando al frontend. Fijar retención y límites de stream según las sesiones del piloto.

Los tokens pueden agruparse en pequeños bloques para no escribir una transacción por token. Conservar orden y tiempos reales de bloque; un bloque no equivale necesariamente a un token. Guardar respuesta original completa para auditar validación y truncamiento.

## 5. Dos clases de streaming

El flujo interno de LiteRT es SSE de completions. La API propia lo convierte en eventos del dominio. No reenviar a ciegas todo el stream al usuario ni ejecutar una herramienta mientras sus argumentos aún están incompletos.

Texto provisional puede mostrarse con esa etiqueta, pero no se acepta como evidencia ni se publica como respuesta final hasta validar. En evaluación estricta, es preferible transmitir estados y mantener oculta la respuesta estructurada hasta su validación; así no se presenta una afirmación descartada como salida aceptada.

Si no se necesita conversación bidireccional continua, HTTP + SSE cubre iniciar, seguir y cancelar. WebSocket se justificaría por control bidireccional frecuente o audio, fuera del alcance actual. MQTT queda para el plano de sensores; no hace falta conectarlo directamente al navegador.

## 6. Cancelación, caída y plazos

Cerrar SSE no cancela una sesión: una pestaña puede cerrarse sin detener un experimento. La cancelación explícita es un comando HTTP persistido. Encolado: eliminar del trabajo pendiente. En ejecución: impedir nuevas acciones y solicitar cancelación al worker/runtime.

Si el runtime no confirma detención, conservar estado de cancelación pendiente y el recurso ocupado. No admitir otra inferencia pesada sobre un cálculo que sigue activo. Si se usa un worker de proceso, definir apagado y recuperación sin recargar otros componentes arbitrariamente. El comportamiento de cancelación del paquete LiteRT-LM instalado debe probarse.

Al reiniciar la API, marcar sesiones no terminales como interrumpidas. Se pueden consultar sus registros; no retomar acciones físicas automáticamente sin una política explícita. Un fallo de escritura impide afirmar que la ejecución quedó registrada; emitir error y detener el ensayo si compromete trazabilidad.

## 7. Medición del frontend y del backend

El backend registra reloj monotónico por proceso y tiempos UTC para correlación. El navegador registra envío, primer evento y visualización. No restar directamente relojes monotónicos de máquinas diferentes.

Separar:

```text
latencia del backend = cola + adquisición + preprocesamiento + inferencia + validación + persistencia
latencia percibida = transporte de petición + backend + transporte de respuesta + renderizado
```

Los términos pueden solaparse si se usa streaming o trabajo concurrente; usar intervalos del trace para evitar sumarlos dos veces. El primer heartbeat no es primer token y el primer token no es primera respuesta validada.

## 8. Acceso y datos

Bind en loopback o IP de Tailscale; reglas de acceso limitadas al grupo de prueba. CORS no es autenticación. Si se usa `EventSource` nativo, no se pueden añadir cabeceras arbitrarias como en `fetch`; resolver acceso con sesión del mismo origen o con `fetch` que lea SSE y autorización por cabecera. No poner secretos en query strings registradas en logs.

Validar tamaño en bytes y dimensiones decodificadas de imagen, tipo real y orientación. Usar IDs de artefactos generados por servidor; no permitir rutas de filesystem ni URLs remotas libres que conviertan al servidor en un cliente SSRF. La API propia no expone el catálogo completo del registro LiteRT-LM a usuarios no autorizados.

Cámara y anotaciones requieren controles de acceso y política de retención. No emitir fotos completas ni base64 dentro de cada evento. Una vista de imagen es acceso explícito al artefacto autorizado. La autorización institucional y el consentimiento aplicable están pendientes de documentación efectiva, según el protocolo de tesis; esta propuesta no los concede.

## 9. Prueba de aceptación antes del frontend

Usar un cliente de terminal y herramientas simuladas: crear sesión, obtener SSE, desconectar tras cierto ID, reconectar sin huecos, repetir POST sin duplicar sesión, cancelar y recuperar el final. Probar consumidor lento, cola llena, reinicio, error dentro del stream y una acción nativa que tarda en detenerse.

Solo después construir la pantalla: cronología FSM, panel contextual con frescura/regiones, resultados y métricas. El frontend no debe inferir métricas científicas contando mensajes SSE.

La pantalla también incluye interruptores de disponibilidad lógica, programación de fallos, formulario de vatios y botón de descarga CSV/ZIP. Un cambio se muestra primero como pendiente y después como aplicado según el acuse del backend; el instante del click no se presenta como hora de efecto garantizada. La disponibilidad real y la simulada aparecen separadas.

Fuentes: [S02, S08–S12, S18–S20](09-fuentes.md). Los endpoints y las garantías de persistencia son diseño propuesto, no capacidades ya presentes en el servidor LiteRT-LM.
