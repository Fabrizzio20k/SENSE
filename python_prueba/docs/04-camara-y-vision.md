# 04. Cámara, YOLO y visión directa

## 1. Dos herramientas visuales diferentes

| Necesidad | Ruta propuesta | Salida |
|---|---|---|
| Conteo visible de personas | Picamera2 → YOLO26n NCNN → fusión de cajas si hay mosaico | Conteo estimado, cajas, región, tiempo y calidad. |
| Descripción o pregunta semántica sobre escena | Imagen → Gemma 4 E2B multimodal | Texto/estructura con limitaciones y evidencia visual identificada. |

Para un conteo concreto, no ejecutar también Gemma «por si acaso». Para describir escena, no ejecutar YOLO si su resultado no es necesario. Si se usan ambos sobre la misma escena, compartir una captura identificada para evitar sumar dos adquisiciones y mezclar instantes.

El fallo de Vulkan con Qwen/llama.cpp comunicado en la sesión no demuestra que YOLO/NCNN tenga el mismo fallo: son motores y operaciones diferentes. Tampoco justifica activar Vulkan en NCNN sin medirlo. Mantener CPU como base y evaluar cualquier backend adicional como experimento aparte.

## 2. Revisión del código de conteo compartido

### Exportación frente a inferencia

El ejemplo exporta `imgsz=320`, pero luego solicita `imgsz=640` al modelo exportado. Verificar la dimensión efectiva en metadata/grafo y la versión de Ultralytics; el argumento de predicción no demuestra que un grafo exportado cambie de forma. Para comparar, exportar explícitamente artefactos 320 y 640 y medirlos con sus dimensiones compatibles [S03].

`quantize=16` corresponde a FP16 en la documentación actual de NCNN; no significa INT8. Fijar versión de Ultralytics y registrar precisión real y hash del artefacto. No volver a exportar pesos durante una medición.

En la primera versión Python, `prepare.py` automatiza esa exportación antes de aceptar sesiones si falta la carpeta; reutiliza una carpeta válida y conserva/rechaza una inválida. El preparador registra parámetros y versiones; `vision.py` y el arranque comparten validación de artefacto. Esa validación por sí sola no ejecuta una inferencia. Por instrucción posterior del autor, el arranque además comprueba una captura real y su conteo antes de admitir sesiones, con imagen temporal eliminada y resumen en preflight. Rutas, comandos y límites están en el [README](../README.md#preparación-en-la-raspberry) y la justificación en [16](16-version-python.md#corrección-comunicada-por-el-autor-arranque-funcional-e-interfaz).

### Mosaicos y costo

El script reduce el ancho a un máximo de 1600; no limita el lado mayor en orientación vertical. Con mosaico 640 y solape 160, el paso es 480. Una imagen de 1600 × 1200 produce tres posiciones horizontales y tres verticales: **nueve inferencias**. Para una captura 3280 × 2464 reducida por ancho, el resultado es aproximadamente 1600 × 1202 y también nueve mosaicos.

No confundir tamaño del mosaico con entrada de red. Un mosaico 640 puede acabar redimensionado a una entrada 320 si ese es el grafo exportado. El tiempo incluye el número de mosaicos, sus transformaciones y la combinación final.

La idea ayuda cuando las personas lejanas se vuelven demasiado pequeñas en una imagen global, pero debe activarse por un perfil de conteo definido, no como ruta rápida por defecto. Comparar primero una pasada a 320 y a 640 sobre el mismo campo, y después mosaicos solo si la exactitud lo necesita.

### NMS y umbrales

La función `nms(cajas, puntajes, umbral)` recibe `umbral`, pero compara contra la variable global `IOU_NMS`. Hoy coinciden y puede pasar desapercibido; al variar parámetros el experimento podría no aplicar el valor solicitado. Debe corregirse al implementar el adaptador y cubrirse con un caso donde el argumento difiera del global.

YOLO26 tiene inferencia de detección end-to-end sin NMS en su diseño publicado [S04]. Eso no elimina la duplicación entre mosaicos: combinar cajas de capturas solapadas sigue requiriendo una regla global. Esa regla puede eliminar personas distintas muy solapadas o conservar fragmentos duplicados. Evaluar con multitudes/oclusiones y conservar cajas antes y después de fusión.

`conf=0.15` es un umbral permisivo, no una garantía de recall ni probabilidad calibrada. Elegirlo con piloto y congelarlo. El número impreso por `print(len(indices))` no alcanza para auditar calidad: falta saber imagen, región, dimensiones, tiempos, scores, fallos y versión del detector.

## 3. Contrato de conteo propuesto

```json
{
  "status": "ok",
  "artifact_id": "image-001",
  "observation_id": "vision-001",
  "scope_id": "camera-roi-1",
  "captured_at": "2026-10-17T18:00:00Z",
  "processed_at": "2026-10-17T18:00:01Z",
  "visible_person_count": 3,
  "image_size": [640, 480],
  "model_input_size": [320, 320],
  "tile_count": 1,
  "boxes": [],
  "quality_flags": [],
  "model_ref": "yolo26n-ncnn-example"
}
```

Los valores son ilustrativos y `boxes` se completaría en implementación. Un fallo produce `status=error` y conteo `null`; una inferencia sin detecciones produce cero detecciones con sus condiciones, no una prueba absoluta de aula vacía. Separar conteo visual de presencia inferida y de cantidad real de personas.

Mantener coordenadas en un espacio documentado: imagen original o imagen redimensionada, con transformación y ROI. No comparar cajas en diferentes escalas. Ocultar o difuminar imágenes de visualización no altera la evidencia original que se evalúa; registrar cualquier procesamiento aplicado a la inferencia.

## 4. Captura con Picamera2

El ejemplo inicia cámara, espera dos segundos, captura a 3280 × 2464 y la detiene. Es una buena prueba de hardware, pero cada invocación paga inicialización, estabilización y codificación de una imagen grande.

Comparar dos estrategias en el piloto:

- **Bajo demanda real:** configurar, iniciar, estabilizar, capturar y liberar. Incluye su latencia y costo completo.
- **Sesión de cámara residente:** mantener preparada o en ejecución según soporte y configuración. Puede reducir espera pero consumir mientras no se usa. No describirla como cámara apagada entre consultas.

La elección debe ser igual para A–D cuando se quiera aislar política. Diferencias de ciclo de vida son otro factor experimental. La cámara puede tener un único dueño; evitar dos scripts/servicios intentando abrirla simultáneamente.

Adquirir píxeles y metadatos del mismo request cuando se necesite correspondencia precisa. Registrar timestamp de sensor y su dominio de reloj, exposición y configuración. El instante posterior a `capture_file` es de finalización, no necesariamente de exposición. Picamera2 documenta `SensorTimestamp`; no asumir equivalencia exacta con UTC ni con otro reloj sin comprobar plataforma y versión [S07].

Durante fallos, liberar recursos en `finally` y marcar timeout/error, no entregar un archivo anterior como si fuera una nueva captura. Para procesos trabajadores usar argumentos tipados y directorios de artefactos controlados, sin concatenar órdenes shell.

### Entorno Python de la cámara

En Raspberry Pi OS, Picamera2/libcamera suelen venir de paquetes del sistema. Comprobar la compatibilidad ABI con el intérprete elegido; un entorno uv aislado con otra versión de Python puede no importarlos. Usar un entorno compatible con los paquetes del sistema o un worker de cámara con el Python del sistema. La selección concreta se resuelve tras Q04; no prescribir Python 3.13 para todo el hardware por defecto.

## 5. Resolución y redimensionado de Gemma

Gemma 4 admite procesamiento visual con presupuestos de tokens; su documentación general enumera 70, 140, 280, 560 y 1120 [S13]. Eso no demuestra qué presupuesto ni qué dimensiones fueron fijados en el `.litertlm` descargado. La configuración del CLI consultada no documenta un selector universal de ese presupuesto para el servidor [S01].

Por tanto, no asegurar que reducir de 480 a 320 acorta el encoder: puede terminar usando la misma representación interna. Sí puede reducir envío, decodificación y detalles disponibles. Tampoco identificar los 29,12 s hasta el primer fragmento con «tiempo puro de encoder»: incluye otras etapas.

Propuesta de ensayo: misma imagen y pregunta, lado mayor 320, 480 y 640, proporción conservada, sin ampliar imágenes pequeñas. Registrar dimensiones originales y enviadas, bytes JPEG, tiempo de transferencia, latencia hasta primer contenido, duración de salida y exactitud. Si el runtime expone tokens visuales/tiempo de encoder, registrarlos; si no, declararlos no observados.

El límite 480 del prototipo es un punto inicial de adquisición/envío, no una optimización interna demostrada. Para texto pequeño y personas lejanas puede ser insuficiente. Un recorte orientado a tarea requiere registrar que el alcance espacial cambió; no contar personas fuera del recorte como errores del detector.

## 6. Perfiles candidatos de piloto

| Perfil | Objetivo | Entrada | Activación |
|---|---|---|---|
| Conteo rápido | Personas grandes en región conocida | Imagen global, modelo NCNN 320 | Falta conteo relevante. |
| Conteo de mayor detalle | Personas pequeñas / región amplia | Modelo 640 compatible o mosaicos definidos | Si el piloto justifica su costo para ese escenario. |
| Descripción | Pregunta visual semántica | Gemma, lado mayor inicialmente 480 | Solicitud explícita o variante experimental. |

No activar mayor resolución basándose únicamente en el score autodeclarado del SLM. Un score YOLO tampoco establece cuánto falta contar. Validar cada perfil contra anotación humana y conservar casos no evaluables.

Fuentes y alcance de verificación: [S03, S04, S07, S13](09-fuentes.md). No se ejecutaron cámara ni YOLO en esta investigación.
