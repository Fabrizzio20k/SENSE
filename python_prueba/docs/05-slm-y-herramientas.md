# 05. Gemma, agentes y razonamiento condicional

## 1. Un modelo, funciones especializadas

Los agentes del prototipo son ingesta ambiental, presencia, visión e interpretación, coordinados por una política. Solo el último necesita generación de lenguaje. No cargar una instancia de Gemma para cada sensor ni replicar una conversación de planificador/ejecutor/verificador si una tabla de reglas ya determina la siguiente acción.

LEAF estudia expertos SLM y un motor FSM; su resultado no obliga a copiar su entrenamiento ni a esperar su desempeño en una Pi. ReAct demuestra una forma de intercalar acciones y razonamiento, pero su evidencia no establece que un bucle generativo sea necesario para este catálogo de tareas [S15, S16]. La elección de una FSM sencilla es una propuesta para reducir llamadas y facilitar atribución de fallos.

## 2. Catálogo mínimo de herramientas

| Operación | Entrada acotada | Resultado | Dueño de la decisión |
|---|---|---|---|
| `read_context` | Región y campos permitidos | Snapshot y calidad | FSM/política. |
| `environment_trend` | Magnitud y ventana válida | Diferencia/tendencia calculada y muestras | Backend. |
| `count_people` | Cámara/ROI registrada, perfil de piloto | Conteo estimado y evidencia | FSM si la tarea lo necesita. |
| `describe_image` | Artifact ID permitido y pregunta | Descripción visual validada | Ruta visual explícita. |
| `interpret_context` | Snapshot ID y pregunta conocida | Interpretación estructurada | Solo tras guardas. |

No son cinco microservicios ni necesariamente cinco herramientas expuestas al modelo. El MVP puede ejecutar las primeras cuatro directamente desde Python y usar Gemma solo en la última o en descripción. Al SLM se le expone un catálogo limitado solo si la interacción natural realmente necesita selección de herramienta.

La herramienta de captura puede ser interna al adaptador de visión; no pedir al modelo una segunda llamada para descubrir que debe capturar antes de contar. No ofrecer `run_python`, `run_shell`, instalación de paquetes, rutas arbitrarias ni acceso libre al broker en la API del prototipo.

## 3. Qué significa activar razonamiento

Separar dos decisiones:

1. **Invocar SLM:** cuesta prefill y generación incluso con thinking desactivado.
2. **Thinking interno:** existe en el motor, pero queda desactivado y fuera de los experimentos por decisión del autor.

El protocolo D interpreta con `thinking=false`, siempre. Aquí «activar razonamiento» significa llamar al SLM. La política básica debería permitir:

| Situación | Acción |
|---|---|
| Dato numérico vigente solicitado directamente | Responder por reglas. |
| Faltan datos esenciales | Adquirir modalidad capaz o abstenerse. |
| Se pide explicar una discrepancia con evidencia suficiente | Invocar intérprete sin thinking; etiquetar hipótesis. |
| Falla herramienta por motivo conocido | Manejo determinista; no replanificar generativamente por defecto. |
| Salida SLM no válida | Fallback o abstención; reintento único solo como variante medida. |

No se construirá una opción para activar thinking ni una comparación sobre ese modo. Usar guardas objetivas y presupuesto para decidir si se invoca al SLM; no «confianza 0.8» inventada por el modelo. La calibración de scores es un problema empírico distinto [S14].

## 4. Entrada y salida propuestas

Enviar al modelo únicamente pregunta, alcance, instante y evidencia seleccionada, incluidas sus limitaciones. No incluir toda la telemetría histórica ni un chat de duración creciente. El backend calcula diferencias, antigüedad y conflictos antes de construir el prompt.

Ejemplo de respuesta estructurada propuesta:

```json
{
  "status": "partial",
  "observed": [
    {"claim": "El radar detecta presencia en su región.", "evidence_ids": ["radar-017"]}
  ],
  "inferred": [],
  "unknown": ["Número actual de personas visibles"],
  "requested_information": ["fresh_visible_count"],
  "recommendations": [],
  "answer": "Hay detección de presencia por radar; no hay un conteo visual vigente."
}
```

`requested_information` no ejecuta nada automáticamente. La política valida si es pertinente, no repetido, permitido y financiable. En el contraste C–D de interpretación, la adquisición queda cerrada: esas peticiones se puntúan, sin dar evidencia extra a D.

Validar con esquema y reglas semánticas acotadas: IDs existentes, campos permitidos, tipo de magnitud, región y tiempos. Un JSON válido no demuestra que la explicación sea cierta; la rúbrica humana mide lo que el validador no puede garantizar. Si hay contradicción numérica con el snapshot, rechazar o sustituir esa parte por una plantilla determinista.

No almacenar ni mostrar pensamiento interno como si fuera justificación verificable. La justificación auditable es la decisión de la política, sus guardas y referencias a observaciones.

## 5. Compatibilidad LiteRT-LM: hallazgos verificables

La documentación confirma configuración por modelo y API de chat con streaming [S01, S02]. El código upstream consultado muestra parsing de herramientas, continuación por mensajes y salida de `tool_calls`; además, desactiva su ejecución automática [S18]. Esto respalda un cliente que valida y ejecuta herramientas localmente, pero **no prueba la versión instalada ni la fiabilidad de Gemma eligiéndolas**.

En las fuentes upstream revisadas, `reasoning_effort=none` desactiva thinking; otros esfuerzos lo activan sin un mapeo fino de presupuesto. El parser de salida estructurada admite JSON/schema [S19]. El handler usa `max_completion_tokens` [S18]. No asumir que `max_tokens` limita una versión que solo lee el otro campo.

El servidor inspeccionado conserva un motor y lo reinicializa si cambia su configuración; usa `HTTPServer`. Su llamada a `Engine` no pasa explícitamente `cpu_thread_count` [S20]. Esto es una alerta de compatibilidad, no prueba de que el paquete de la Pi ignore hilos por todos sus caminos. Antes de afirmar «4 hilos efectivos», inspeccionar la versión instalada, su implementación y métricas de ejecución.

Mantener un único motor residente con thinking desactivado en su configuración y comprobar que las peticiones no lo reactiven. La API propia no permite al cliente habilitarlo. No crear otros aliases o procesos para experimentar con ese modo.

### Prueba de capacidades antes de integrar

1. Registrar `uvx litert-lm --version`, `serve --help`, metadata y hash del bundle. Fijar versión para ensayos finales; no depender de actualizaciones implícitas de `uvx`.
2. Texto ligero repetido: observar carga fría y caliente; verificar que el límite de salida efectivo funciona con `max_completion_tokens`.
3. Imagen local conocida y pregunta explícita: verificar respuesta y tiempos, sin comparar aún con YOLO.
4. Herramienta ficticia de solo lectura: exigir un nombre y argumentos conocidos; ejecutar el stub en el cliente y enviar su resultado para continuación.
5. Herramienta inexistente y argumentos inválidos: deben rechazarse sin ejecución.
6. Si se usa salida restringida, probar el subconjunto de JSON Schema realmente soportado, longitud y truncamiento.
7. Comprobar que thinking permanece desactivado. No asumir que ocultar su texto elimina el cómputo; no ejecutar pruebas con thinking activado.
8. Cancelar una respuesta larga y verificar que el motor deja de calcular antes de admitir otro trabajo.

Estas pruebas aún no se ejecutaron en la Raspberry. Tener una API compatible en nombre no garantiza equivalencia completa de campos y semántica entre versiones.

## 6. Defensa ante entradas y resultados no fiables

Los textos de usuarios, OCR, imágenes y payloads son datos, no instrucciones de sistema. No permitir que texto en una imagen habilite herramientas, cambie límites o solicite secretos. El backend conserva permisos, regiones y presupuesto fuera del prompt.

Cada llamada tiene timeout, tamaño máximo y salida acotada. Si una respuesta llega después de una cancelación o vencimiento, guardarla como tardía para diagnóstico cuando corresponda, pero no aceptarla como resultado vigente. Un retry generativo se registra como una nueva invocación, con sus tokens y costo.

El error observado sobre mano y mechero se conserva como ejemplo de alucinación de conocimiento general. El uso de hechos estructurados y herramientas reduce tareas que dependen de ese conocimiento, pero no garantiza exactitud. H3 debe poder resultar negativa sin que se considere un fallo del diseño experimental.

Fuentes: [S01, S02, S14–S20](09-fuentes.md). El protocolo propone probar capacidades; no presupone que todas estén presentes en el paquete ya instalado.
