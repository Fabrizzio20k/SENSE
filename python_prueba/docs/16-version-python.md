# 16. Entrega de la primera versión Python

## Estado y alcance de esta entrega

El autor autorizó implementar la primera versión y después precisó: **no ejecutar aquí**, preparar los archivos para subirlos a la Raspberry y priorizar funcionalidad sobre UI. La versión ampliada se entrega escrita y revisada por lectura; no se ejecutaron su arranque, sus pruebas ni sus adaptadores de hardware después de esa instrucción. No se usa el código Rust existente.

Antes de esa precisión se instalaron dependencias del núcleo en el entorno local y se verificó una versión anterior de sensores/reglas. Eso no verifica el código ampliado. El intento de iniciar un broker temporal falló por permisos y la solicitud posterior fue interrumpida; no se presenta una prueba real MQTT, de cámara o de Gemma como completada.

La guía de traslado, instalación, configuración, rutas HTTP y ejemplos utilizables está en [README de Python](../README.md). No copiar el entorno virtual de macOS a la Pi. Resolver allí dependencias para el Python compatible con Picamera2; el lock temporal del núcleo se retiró al cambiar dependencias.

Por petición posterior del autor, [requirements.txt](../requirements.txt) es la lista única sin fijar versiones, incluida Ultralytics; `pyproject.toml` consume ese archivo. La instalación documentada usa `pip install --upgrade -r requirements.txt` para resolver versiones estables recientes compatibles. No se consultaron ni instalaron releases aquí. Esto facilita la instalación, pero no demuestra compatibilidad ARM64/Picamera2. Antes del piloto se debe archivar el entorno resuelto y mantenerlo constante entre repeticiones; el manifiesto amplía las versiones registradas a cliente, imagen, detector y librerías numéricas, con `null` para distribuciones ausentes.

La configuración carga automáticamente `python_prueba/.env` con `python-dotenv` antes de validar ajustes. Se usa una ruta explícita relativa al código para evitar depender del directorio de trabajo o cargar archivos de otras carpetas. El entorno del proceso tiene prioridad; sin archivo se conservan los valores predeterminados. `.env.example` solo sirve de plantilla y no se sobrescribe un `.env` existente. Esta decisión elimina pasos manuales de exportación y mantiene la misma validación de tipos, rangos y comunicación local. Las credenciales no se agregan al manifiesto.

## Mapa funcional

| Función | Archivo responsable | Comportamiento escrito |
|---|---|---|
| Contrato MQTT y calidad parcial | [context.py](../context.py), [mqtt_ingest.py](../mqtt_ingest.py) | Una suscripción; validación por fuente; tipos, zona horaria, duplicados, retenidos y orden. Un ENS160 inválido no borra SHT40/radar. |
| Umbrales y contexto | [context.py](../context.py) | Ventanas 30/120 s, apertura 10 s, recuperación a media banda 20 s, radar 2 s, watchdog de recepción 7 s. Perfil candidato centralizado. |
| FSM y episodios | [orchestrator.py](../orchestrator.py) | Estados por episodio, snapshots con hash, respuestas por reglas, historial y degradación sin fabricar ceros. |
| A–D y presupuestos | [actions.py](../actions.py) | Periódica, entrada radar, renovación adaptativa y la misma adquisición con interpretación condicional. Cola máxima 8 y una acción pesada. |
| Cámara y conteo | [vision.py](../vision.py) | Worker persistente con NCNN; cámara bajo demanda y liberada al capturar. Captura/metadata del mismo request, verificación de imgsz, clase person, hash de modelo y fusión global si hay mosaicos. |
| Preparación previa | [prepare.py](../prepare.py), [runtime.py](../runtime.py) | Artefacto NCNN, Gemma, captura/conteo reales y lecturas nuevas por sensor; diagnóstico en segundo plano con admisión bloqueada hasta éxito. |
| Gemma estructurado | [slm.py](../slm.py) | HTTP local, thinking solicitado desactivado, salida limitada, esquema y referencias, cero herramientas libres y cero reintentos generativos automáticos. |
| Descripción de imagen | [actions.py](../actions.py), [slm.py](../slm.py) | Ruta `E_visual` explícita; captura sin YOLO para describir, o imagen subida por ID, envío con lado mayor 480. |
| Fallos y restauración | [orchestrator.py](../orchestrator.py) | Sensores, cámara e intérprete: disabled/drop/freeze/error; planes sin solapamiento; versión de disponibilidad y supresión de resultados tardíos. |
| Ciclo de vida y replay | [runtime.py](../runtime.py) | Un escritor lógico, ingesta independiente de acciones pesadas, reloj monotónico y replay MQTT separado de hardware. |
| Recursos y W | [experiment.py](../experiment.py) | Recursos nominales 1 Hz; ausentes null; CPU de procesos sin normalización engañosa; W/contador y correcciones conservadas. |
| API y SSE | [app.py](../app.py) | Admisión idempotente, una sesión activa, cancelación, preguntas, artefactos, anotaciones, evaluación, eventos recuperables y exportación. |
| Persistencia y exportación | [store.py](../store.py) | SQLite/WAL, interrupción tras reinicio, doce tablas CSV, JSONL, manifiesto, hashes y corte común por secuencia. |
| Pantalla básica | [index.html](../static/index.html) | Monitoreo, preguntas, intervenciones y exportación. El backend sigue trabajando sin navegador. No es un frontend de evaluación ciega con cuentas separadas. |

Los archivos contienen implementación, no resultados de rendimiento ni validación experimental. Las dependencias de cámara se importan dentro del worker; los componentes existentes de Mosquitto y LiteRT-LM no se arrancan ni se reconfiguran desde la API.

## Invariantes de diseño

1. La ausencia de datos es desconocida/indisponible; nunca equivale a cero personas o un valor ambiental cero.
2. El timestamp global del productor no se convierte en tiempo de adquisición individual sin verificación. La recepción monotónica es una aproximación explícita para las ventanas de esta versión.
3. Un mensaje retenido/repetido no rejuvenece una medición; un resultado visual tardío conserva su tiempo de captura. Las imágenes subidas no renuevan el conteo en vivo.
4. Se selecciona radar previo a captura. Cobertura o reloj desconocidos producen `not_comparable`, no conflicto confirmado. Una declaración de reloj debe estar sustentada por medición en la Pi.
5. D no utiliza peticiones del SLM para cambiar adquisición ni conseguir evidencia adicional frente a C. Una pregunta directa no exige generación. Un snapshot persistido de C se puede interpretar desde D sin reconstruirlo.
6. Fallos simulados no apagan hardware ni implican ahorro por corte de alimentación. Restaurar requiere evidencia nueva, y un cambio de versión durante una acción impide aceptar su resultado.
7. Cola y seguimientos son finitos. Cada episodio permite una ejecución visual y una interpretación; los seguimientos crean otros episodios enlazados. Una fuente que falla no causa reintentos generativos ilimitados.
8. Cancelar HTTP no prueba cancelación remota. Una reserva SLM no confirmada persiste y bloquea trabajo pesado posterior, hasta confirmar manualmente que el runtime está inactivo. Detener el worker visual requiere confirmar salida del proceso.
9. Las anotaciones humanas, planes futuros y evaluaciones no se incluyen como evidencia para el modelo. Las interpretaciones del modelo tampoco se reciclan como nuevas mediciones.
10. La respuesta/evento se persiste antes de transmitirlo. SSE recupera historial desde SQLite y no mantiene una cola ilimitada por navegador. Reiniciar no reejecuta acciones antiguas.

## Nuevos valores candidatos operativos

Los valores ambientales acordados siguen en [14](14-umbrales-y-activacion.md). Para permitir una primera ejecución se añadió un perfil operativo explícito en `ACQUISITION_PROFILE`: visión periódica y TTL de conteo 30 s, cooldown 5 s, timeout visual 90 s, timeout SLM 120 s, episodio 240 s incluyendo cola, salida máxima 384 tokens y hasta dos seguimientos cada 30 s dentro de 180 s.

La reserva inicial es 512 MiB y la guarda térmica 80 °C cuando existe lectura. Estos son candidatos de ingeniería para pilotar, **no valores derivados del registro de 490 mensajes**, ni prueba de tiempos integrados o RAM suficiente para cualquier modelo. Los hashes de perfil/configuración los acompañan en el manifiesto; no se permite declarar ensayos finales con este perfil exploratorio.

## Preparación automática y justificación de las decisiones

Esta ampliación responde a la petición de comprobar Gemma local y reutilizar o convertir YOLO antes de ejecutar el experimento. Es una decisión de implementación para el piloto; no se presenta como resultado empírico ni como umbral derivado de la telemetría.

| Decisión implementada | Fundamento y límite verificable |
|---|---|
| Gemma por defecto en `127.0.0.1:8080`, modelo `gemma4-e2b` | Coincide con el `run-litert.sh` de la raíz inspeccionado. Las variables son opcionales; se restringe HTTP a loopback y se omiten proxies del entorno. El script sigue siendo responsable del servidor. |
| Sondeo `GET /v1/models` con límite de tiempo/tamaño y coincidencia exacta de modelo | Distingue servidor inaccesible, respuesta incompatible y modelo ausente sin solicitar generación. `generation_verified=false`: el catálogo no demuestra inferencia, carga residente ni thinking efectivo. |
| Calentamiento multimodal `gemma-image-warmup-v1`, habilitado por defecto | Usa `static/image.png` y solicita describir lo visible con una sola palabra en español; máximo 16 tokens, temperatura 0, `reasoning_effort=none`, plazo total 120 s. Ejercita la petición conjunta de imagen y texto con una respuesta breve completa. Es un protocolo candidato solicitado por el autor; no demuestra reducción de latencia hasta medirla. |
| Misma transformación visual que en las consultas | RGB, lado mayor 480 por defecto (según configuración visual de Gemma), JPEG calidad 85 y `image_url` con datos en la petición local. Se conservan hashes de original/enviado, dimensiones y bytes; el hash de adquisición incluye el perfil de calentamiento y el hash del JPEG usado. No usa cámara ni YOLO; un archivo ausente/corrupto falla antes del HTTP y libera la reserva local. |
| Calentamiento fuera de sesión, una vez por arranque/preparación explícita | Su duración, prompt, respuesta y uso reportado se guardan en `gemma_warmup`, en preflight y manifiesto, sin incorporarlos a episodios ni recuentos de la sesión. Las admisiones siguientes reutilizan el éxito observado; no generan otra respuesta de prueba. Un fallo no produce reintentos automáticos dentro de la misma preparación. |
| Opción `SENSE_SLM_WARMUP=0` para ensayos en frío | Permite omitir la petición de calentamiento y registra la elección, también en el hash de adquisición. Requiere controlar por separado reinicio del servidor y uso previo: omisión no demuestra estado frío. C y D deben compararse con la misma condición inicial y configuración de calentamiento. |
| `/health` pasivo | Presenta los últimos chequeos de modelos/cámara y actualiza la antigüedad de recepción MQTT, sin sondear ni inferir. El panel puede consultarlo periódicamente sin peticiones adicionales al servidor de Gemma. |
| Exportación NCNN solo si falta la carpeta | Conserva trabajo previo y evita variación involuntaria del artefacto entre repeticiones. Se valida metadata, archivos no vacíos, tamaño de entrada y clase `person`; `inference_verified=false`. |
| `format=ncnn`, `imgsz=320`, `quantize=16`, CPU | Reproduce los parámetros de conversión aportados por el autor, con CPU explícita. FP16 solicitado no prueba precisión efectiva en todas las operaciones. Una red 640 requiere artefacto y configuración 640 coincidentes. |
| Exportación en subproceso y carpeta temporal, publicación al finalizar | Aísla el cambio de directorio y las importaciones pesadas. Un fallo no publica un directorio parcial; una carpeta previa inválida se conserva para corrección. Un bloqueo por destino serializa conversiones del preparador. |
| Exclusión mutua entre preparación y admisión | Impide iniciar una sesión viva hasta completar la comprobación de todos los componentes, incluso `rules-v1`. La pantalla de diagnóstico sigue disponible si algo falla. Repeticiones idempotentes recuperan la sesión sin repetir preparación. |
| Registro de procedencia y hashes | `preparation.json` conserva parámetros, versiones, hash de pesos y duración de nuevas conversiones; `preflight.json` conserva el diagnóstico y el manifiesto de sesión incluye su copia. Para un export antiguo sin procedencia se registran hashes actuales sin atribuirle parámetros desconocidos. |

Rutas predeterminadas: `python_prueba/data/models/yolo26n.pt` y `python_prueba/data/models/yolo26n_320_ncnn_model`; cambian bajo `SENSE_DATA_DIR` o mediante rutas explícitas. Solo el peso estándar `yolo26n.pt` ausente admite descarga automática; los pesos personalizados deben existir localmente. No se instalan dependencias desde el preparador. El replay no consulta Gemma ni convierte modelos.

La conversión, validación, calentamiento y captura/conteo de comprobación ocurren antes del reloj experimental. Aun así, convertir o generar puede alterar temperatura y leer hashes puede poblar caché de archivos del sistema operativo: **fuera de la ventana no significa sin efecto sobre el estado inicial**. Antes del piloto se debe fijar y registrar la estabilización térmica y la condición inicial. La comprobación visual deja normalmente el worker/modelo YOLO residente, declarado en `camera_model_resident_before_run`; no presentar las sesiones posteriores como primera inferencia en frío. El calentamiento con imagen reemplaza el anterior «OK» solo de texto. Registra `image_request_completed=true`; no certifica la corrección semántica de la palabra, todas las operaciones internas del encoder (`visual_encoder_verified=false`) ni residencia futura de Gemma. Una respuesta sin pensamiento visible tampoco certifica thinking efectivo desactivado.

La ampliación de calentamiento sustituyó la decisión inicial de comprobar únicamente el catálogo; la comprobación funcional posterior amplía además la admisión a todos los componentes. `/health` ya no efectúa sondeos. Si LiteRT-LM se reinicia por fuera, repetir explícitamente la preparación; un catálogo idéntico no identifica una nueva instancia del servidor. La admisión viva exige calentamiento exitoso si está habilitado. Timeout/cancelación conservan la reserva persistente del slot hasta confirmación del operador, igual que una inferencia de sesión; una respuesta completa rechazada se registra fallida y libera la reserva.

Para recuperación, `POST /v1/runtime/prepare` con `{}` repite preparación fuera de sesión. Si persiste una reserva de cómputo sin detención confirmada, primero se exige la confirmación del operador ya documentada; un sondeo correcto no libera esa reserva.

## Corrección comunicada por el autor: arranque funcional e interfaz

El autor reportó `crypto.randomUUID is not a function` y solicitó ordenar la pantalla y comprobar una captura, su conteo y una lectura por sensor antes de iniciar. Ese reporte evidencia un fallo de interfaz; **no constituye una prueba exitosa del sistema integrado**. No se identificó mediante una reproducción local, por la restricción vigente de no ejecutar.

| Cambio | Criterio y límite |
|---|---|
| Claves de idempotencia compatibles con HTTP sobre IP | Comprobar disponibilidad de `randomUUID`; usar `getRandomValues` cuando falte y una alternativa con tiempo/contador/aleatoriedad si no existe `crypto`. La clave no es una credencial. Conservarla si se pierde la respuesta de creación evita duplicar una sesión al repetir la petición. |
| Diagnóstico visible mientras se comprueba | Iniciar ingesta MQTT y el ciclo de recepción antes de la tarea de preparación. La API permite ver progreso, pero cualquier nueva sesión viva queda bloqueada hasta completar las condiciones. Fallar una comprobación conserva el diagnóstico y permite repetir, sin un bucle automático de conversiones/inferencias. |
| Foto y conteo reales | Ejecutar el worker existente con Picamera2 y YOLO, plazo 90 s, sin imagen subida. Decodificar el JPEG producido y validar tamaño, hash, referencia del modelo y coherencia entre conteo y cajas; cero personas es admisible. Guardar resumen, duración y procedencia en preflight; eliminar la foto temporal tras el intento. Ejecutar no certifica exactitud del conteo. |
| Una lectura nueva por sensor | Reusar contrato y validación por fuente del sistema. Excluir retenidos y timestamps repetidos/fuera de orden; recibir después del inicio de preparación y conservar antigüedad menor que 7 s al admitir. Esperar como máximo 30 s adicionales después de los chequeos pesados, candidato operativo explícito en `ACQUISITION_PROFILE`. Una lectura no demuestra calibración, tiempo físico ni calentamiento correcto del ENS160. |
| Diagnóstico separado de evidencia experimental | Las lecturas previas y el conteo de prueba no se introducen en las fuentes/historias de la sesión ni satisfacen su conteo vigente. La sesión inicia su propia evidencia y referencia ambiental. El manifiesto conserva el resumen previo como procedencia de preparación. |
| Admisión uniforme | En modo vivo, todas las variantes requieren broker, tres sensores, foto/conteo y Gemma comprobados, con calentamiento según configuración. Esto reemplaza la posibilidad anterior de empezar `rules-v1` con modelos incompletos. El replay mantiene su excepción explícita sin hardware. |
| Panel en tres etapas | Comprobación por componente y repetición; configuración/admisión de sesión; lecturas/decisiones y registro del investigador. Consultas solo habilitadas para variantes compatibles. No utiliza HTML proveniente de mensajes/modelo para representar resultados. |

`POST /v1/runtime/prepare` devuelve **202** y una comprobación en segundo plano. Peticiones repetidas mientras está activa consultan la misma operación. `/health` agrega `preparing`, `can_start_session`, resultado de cámara y estado/edad de recepción de cada sensor. Una reserva en uso no se puede liberar desde `confirm-idle` durante esa comprobación. Las comprobaciones de cámara/modelo son de la última ejecución; no afirman vigilancia continua ni detectan automáticamente un reinicio externo del servidor.

La imagen estática de calentamiento de Gemma se mantiene separada de la captura real usada para comprobar YOLO. Ambas son preparación común y fuera de las métricas de la sesión. Repetir preparación puede cambiar temperatura, residencia de modelos y cachés; registrar la condición inicial de A–D y revisar el protocolo de frío/caliente antes de comparar resultados.

## Pruebas y verificación pendiente

Se dejan pruebas escritas de política, validación, fallos, SSE, persistencia, potencia, exportación, fusión, esquema SLM, cola y snapshots. **No se ejecutaron sobre la entrega ampliada**, por instrucción del autor. Las pruebas sin hardware se pueden correr posteriormente con el comando del README; el adaptador visual y el runtime local necesitan además pruebas reales separadas.

[test_settings.py](../tests/test_settings.py) cubre carga automática desde la ruta del proyecto, valores entre comillas, prioridad del entorno, ausencia de `.env` y mantenimiento de las validaciones; tampoco se ejecutó aquí.

[test_startup.py](../tests/test_startup.py) prepara comprobaciones con foto/conteo simulados, limpieza, sensores nuevos por fuente, mensajes retenidos/repetidos/antiguos, plazo de espera finito y bloqueo de admisión. [test_ui.cjs](../tests/test_ui.cjs) prepara regresiones del generador de claves con y sin las funciones de `crypto`, sin arrancar navegador/API. Las fixtures de política/admisión se actualizaron para declarar explícitamente un diagnóstico simulado. **No se ejecutaron ni se verificó visualmente la interfaz aquí**; Node es solo una opción para esa prueba, no una dependencia de despliegue.

[test_prepare.py](../tests/test_prepare.py) incorpora fixtures de archivos y HTTP simulados: reutilización sin importar el exportador, rechazo conservador de metadata/tamaño/archivos inválidos, parámetros originales de exportación, fallo sin publicación parcial, caché de pesos, procedencia, catálogo correcto/incorrecto/inaccesible, exclusión de admisiones y omisión del sondeo durante una sesión. Añade contrato del calentamiento con imagen, transformación y hashes del JPEG, respuesta de una palabra, archivo ausente/corrupto sin llamada HTTP, respuestas truncadas/con thinking/herramientas, omisión configurable, reutilización al admitir sesión y reserva ante timeout/cancelación o liberación ante error previo al envío. Estas pruebas están escritas, no ejecutadas; sus fixtures no son redes NCNN ejecutables.

En la Pi se deben verificar, antes de evaluar hipótesis: intérprete y ABI Picamera2, colores/formato/metadata de captura, dimensiones efectivas NCNN, conteo y mosaicos en las escenas, compatibilidad de los campos LiteRT-LM, thinking efectivamente desactivado, plazos y cancelación, continuidad de ingesta bajo carga y coste de instrumentación. Si se quiere conservar participantes en fotos, documentar autorización y política de retención antes de habilitarla.

El validador del modelo verifica estructura y pertenencia de referencias; **no certifica la verdad de todas las afirmaciones naturales ni su coherencia numérica completa**. Las evaluaciones humanas siguen siendo necesarias. La API es local, sin cuentas/RBAC ni automatización del tamaño de muestra, adjudicación o análisis estadístico final. Métricas publicadas son descriptivas; no se inventan F1, potencia estadística, ahorro ni picos de energía sin referencia y medición suficientes.
