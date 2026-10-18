# 01. Qué exige realmente la tesis

Fuente local: [main.pdf](main.pdf), SENSE: Resource-Aware Multimodal Small Language Model Agents for Context Understanding on Edge IoT Devices. El autor lo reubicó en esta carpeta. Las páginas físicas 8–48 contienen el planteamiento y la metodología; 49–52, referencias. Portada, índices y páginas preliminares no añaden requisitos funcionales.

## 1. Interpretación del problema

El objetivo no es demostrar que un modelo pequeño responde sobre una foto. Es evaluar si un estado de conocimiento explícito permite adquirir y procesar solo la información necesaria, conservando calidad contextual y caracterizando su costo. Hay tres contribuciones que deben medirse por separado: integrar modalidades, seleccionar activaciones e interpretar con SLM.

La implementación debe distinguir:

1. **Estado físico:** lo que ocurre realmente, parcialmente observable.
2. **Estado de conocimiento:** observaciones, tiempo, alcance, limitaciones y necesidades pendientes.
3. **Estado operativo:** fase actual de la FSM, por ejemplo `VISION`.

Que el sistema esté en `VISION` no significa que haya gente; que el radar no detecte no demuestra que todo el aula esté vacía. Esta separación se establece en §2.1, PDF 28–29 / impresas 21–22.

## 2. Matriz de trazabilidad

| ID | Requisito o restricción | Evidencia del PDF | Consecuencia de diseño | Prueba prevista |
|---|---|---|---|---|
| R01 | Ejecución e inferencia locales en Pi 5 de 8 GB | Alcance, PDF 13–14 / 6–7 | Ninguna ruta depende de inferencia en nube. Frontend remoto no implica cómputo remoto. | Desconectar salida a internet con modelos ya disponibles y ejecutar casos. |
| R02 | Integrar SHT40, ENS160, LD2410C e IMX219 | PDF 13 / 6; §3.4, PDF 42 / 35 | Reutilizar publicación MQTT; adaptador de cámara separado. | Entradas disponibles, ausentes, inválidas y antiguas por fuente. |
| R03 | Conservar procedencia, unidad, tiempo y región | §2.1–2.3, PDF 28–31 / 21–24; tabla 3.1 | Observaciones inmutables y snapshots identificables. | Reconstruir qué evidencia produjo una salida. |
| R04 | Representar desconocido, antiguo y contradictorio | §3.2, PDF 40–41 / 33–34 | No rellenar huecos con cero ni borrar discrepancias. | Pérdida de radar; cámara sin datos; conteo con distinta región. |
| R05 | Activación visual por necesidad concreta | §3.3, PDF 41–42 / 34–35 | Radar positivo no dispara cámara por defecto. | Pregunta solo de presencia sin captura; conteo vencido con una captura. |
| R06 | Control determinista mediante FSM | Tabla 3.2, PDF 42 / 35 | Guardas y decisiones versionadas, con causas registradas. | Cada transición y cada fallo tienen destino y límite. |
| R07 | SLM con evidencia estructurada en la ruta principal | §2.5 y §3.2, PDF 34–35 y 40 / 27–28 y 33 | Ruta YOLO → evidencia → reglas o SLM. | Reglas y SLM reciben un snapshot idéntico. |
| R08 | Separar hechos, inferencias, desconocidos y recomendaciones | Objetivo 4, PDF 12 / 5; §2.5 | Respuesta estructurada con referencias a evidencia. | Rechazar identificadores inventados; puntuar afirmaciones no respaldadas. |
| R09 | Manejar plazos, recursos y degradación | §3.3, PDF 41–42 / 34–35 | Presupuesto global, límites de invocación y salida parcial. | Fuente indispensable fallida y expiración durante inferencia. |
| R10 | Evaluar política y SLM por separado | §3.5, tabla 3.3, PDF 44–45 / 37–38 | Comparadores A–D; prueba emparejada C frente a D. | No permitir que D adquiera más evidencia en el contraste interpretativo. |
| R11 | Referencia humana independiente | PDF 44 / 37; PDF 47–48 / 40–41 | Anotaciones separadas de predicciones y sin sugerencias del modelo. | Subconjunto con doble anotación y discrepancias registradas. |
| R12 | Calidad contextual y costo completo | §3.6–3.7, PDF 45–48 / 38–41 | Medir colas, captura, inferencia, validación y salida; no solo tokens/s. | Cronología de una ejecución de extremo a extremo. |
| R13 | Potencia y energía, distinguiendo método y resolución | PDF 47 / 40, ampliado por instrucción posterior del autor | API para lecturas manuales W y contador Wh/kWh opcional; separar energía estimada por integración de energía leída del contador. | No atribuir picos entre muestras ni sustituir energía con CPU%. |
| R14 | Sin reconocimiento facial ni decisiones críticas | PDF 13–14 / 6–7 | Herramientas de lectura/percepción y recomendaciones no críticas. | No existe herramienta de accionamiento físico en el MVP. |
| R15 | Congelar parámetros después del piloto | PDF 43 y 48 / 36 y 41 | Manifiesto de configuración y conjunto final separado. | Un ensayo referencia hashes y versión de política. |

## 3. Preguntas contextuales que sí debe resolver

Catálogo inicial propuesto; se aprobará antes de la evaluación final.

| Pregunta | Evidencia mínima | Componente que puede bastar | Límite de afirmación |
|---|---|---|---|
| ¿El radar detecta presencia ahora? | LD2410C vigente | Reglas | Solo su cobertura comprobada. |
| ¿Cuántas personas son visibles? | Captura y conteo vigentes en ROI conocida | YOLO + respuesta determinista | Personas detectadas en la imagen; no población total del aula. |
| ¿Cómo cambió la temperatura? | Dos lecturas válidas o ventana temporal definida | Cálculo numérico | Cambio observado; no causa física. |
| ¿Qué indicador ambiental cambió? | ENS160 válido, unidad y calidad | Reglas | eCO2 estimado / TVOC según dispositivo; no CO2 medido ni peligro certificado. |
| ¿Por qué radar y visión difieren? | Evidencia temporal y espacial comparable | Reglas para detectar discrepancia; SLM opcional para explicarla | Explicaciones como hipótesis, no confirmación de causas. |
| ¿Qué falta para responder? | Snapshot con necesidades explícitas | Política determinista | Pedir modalidad capaz de responder, o abstenerse. |
| ¿Qué se ve en esta imagen? | Imagen identificada y pregunta explícita | Gemma multimodal | Variante ampliada, con incertidumbre y costo propios. |

No usar la temperatura ni el eCO2 como sustitutos automáticos de presencia. No pedir al SLM calcular una resta que ya puede calcular el backend. Evitar preguntas generales cuyo éxito dependa de conocimiento científico no contenido en la evidencia: el ejemplo conversacional de mano frente a llama mostró una respuesta plausible pero equivocada.

## 4. Diferencias que deben quedar visibles

### Lenguaje de implementación

El objetivo 2 y §3.2 especifican un orquestador Rust. Por instrucción actual del autor, esta propuesta diseña Python como sistema independiente. Si el experimento final se ejecuta en Python, habrá que actualizar esas secciones y el manifiesto de software. No se propone una migración futura como requisito.

### Visión directa

El PDF dice explícitamente en §3.2 que el SLM recibe observaciones estructuradas y no imágenes crudas. Las pruebas actuales con Gemma multimodal amplían ese alcance. Recomendación: conservar YOLO como vía principal de conteo y tratar la descripción directa como variante `E_visual`, sin atribuir sus resultados al contraste C–D original.

Si se decide que la visión directa sea parte central, antes de los ensayos finales deben modificarse arquitectura, preguntas y comparadores. C con solo cajas de YOLO y D con foto no reciben la misma evidencia.

### Interpretación frente a thinking

En este proyecto, razonamiento SLM significa invocar el modelo para interpretar el contexto. Por instrucción del autor, `thinking=false` queda fijo y no se propone una ablación con thinking activado. La variable experimental es llamar o no al intérprete SLM, con la misma evidencia.

### API y frontend

El PDF no exige SSE, un framework web ni un dashboard; la instrucción posterior del autor sí requiere observación visual continua de decisiones, controles de fallos simulados, introducción de potencia y exportación CSV. Son parte del diseño del prototipo experimental. Las intervenciones cambian las condiciones de entrada de forma registrada; no permiten modificar silenciosamente las reglas de la política.

### Medición manual de potencia

El protocolo escrito contempla energía por diferencia del contador. El autor añade lecturas periódicas de potencia en W introducidas desde la web. El diseño incluye ambos métodos, sin equipararlos: la integración de W muestreados es una estimación y el contador acumulado es otra observación. Esta ampliación debe reflejarse en la metodología final.

## 5. Qué no queda demostrado por el documento

Las hipótesis H1–H3 son propuestas. No existe un resultado de ahorro energético, precisión de conteo, latencia integrada ni superioridad del SLM. La ecuación de utilidad informativa de §2.3 es conceptual; no exige implementar un POMDP ni permite afirmar que se encontró una política óptima.

Los diagramas del capítulo III están pendientes en el PDF. Los diagramas de estos documentos son diseños propuestos a partir de las tablas existentes, no figuras ya aprobadas de la tesis. La revisión bibliográfica del PDF es intencional y acotada; este trabajo no convierte sus afirmaciones de brecha en una búsqueda exhaustiva mundial.
