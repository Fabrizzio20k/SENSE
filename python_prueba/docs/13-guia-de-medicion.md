# 13. Guía de medición: del guion al resultado

Este documento fija las aclaraciones de la conversación. Se utilizará como guía de operación de la futura interfaz. Describe experimentos guiados; no afirma que el software ya implemente estas funciones.

**Actualización del panel (19/10/2026):** se escribió la cola obligatoria de W y el cierre administrativo descritos en el [README](../README.md#lecturas-w-obligatorias-y-cierre) y en [16](16-version-python.md). Solicita W iniciales, cada 30 s y finales, conserva olvidos y exige lectura con tiempo real o motivo de omisión antes de cerrar. No se ejecutó ni valida el protocolo. La adquisición se detiene independientemente de esa revisión. La interfaz no automatiza el resto del guion físico, la referencia humana ni la evaluación final.

## 1. Alcance y distinciones obligatorias

**Escenario** es lo que ocurre o se introduce: ingreso de personas, cambio ambiental, cámara no disponible, etc. **A–D son configuraciones del programa**, no cuatro escenarios físicos. Se repite un guion comparable con cada configuración.

El objetivo es medir calidad contextual, selección de procesamiento, robustez y costo. La salida no tiene que explicar la causa física de todo cambio: puede registrar un hecho, conservar una discrepancia, pedir evidencia o abstenerse. No se ejecutan actuaciones físicas críticas ni se diagnostica seguridad ambiental.

En A/B/C se permite YOLO, que es IA visual. La diferencia es que la interpretación de sus resultados y sensores se hace con reglas. D añade interpretación mediante Gemma, siempre con thinking desactivado. No todo episodio de D llama al modelo y no se concede evidencia adicional a D en el contraste interpretativo C–D.

## 2. Antes de una medición: congelar el perfil

Un ensayo final no empieza con «detectar cualquier cambio». Debe seleccionar un perfil que ya especifique:

| Elemento | Lo que debe estar definido antes de medir |
|---|---|
| Objetivo | Presencia en qué cobertura, conteo en qué ROI y preguntas contextuales previstas. |
| Vigencia | TTL por fuente/tarea y antigüedad máxima del conteo si el objetivo exige mantenerlo. |
| Evento ambiental | Magnitud, línea base, cambio mínimo, duración y criterio de recuperación. |
| Adquisición A | Intervalo periódico visual. |
| Adquisición B | Disparadores simples concretos, por ejemplo transición radar ausencia → presencia. |
| Adquisición C/D | Necesidades que justifican visión, cooldown, límites y presupuesto. |
| Interpretación D | Lista de tipos de episodio que requieren interpretación y evidencia mínima. |
| Seguimiento | Próxima comprobación, máximo de comprobaciones y vencimiento. |
| Referencia | Preguntas, etiquetas humanas, tolerancias y condiciones no evaluables. |
| Instrumentación | Cadencia de recursos, W manuales, tiempos y formato de exportación. |

Los valores se eligen con piloto y quedan versionados. El software debe impedir iniciar una sesión marcada como final con campos experimentales indispensables sin definir. En exploración puede permitir perfiles provisionales, señalándolos como tales.

El catálogo concreto de parámetros y su estado está en [14 — umbrales y activación](14-umbrales-y-activacion.md). El análisis de 490 mensajes y la justificación de candidatos temporales están en [15 — línea base y desfases](15-analisis-linea-base.md). La implementación escrita ya contiene un perfil candidato, todavía sin calibración ni verificación integral en la Pi; ver [16](16-version-python.md). Las cadencias de registro de recursos/potencia no son disparadores del SLM.

## 3. Qué hace cada configuración en el mismo flujo

Todas usan ingesta → contexto → evaluación → acción si corresponde → resultado/registro. Los adaptadores, validación, medición y preguntas permanecen iguales. Cambian las guardas de adquisición y el intérprete.

| Configuración | Cuándo usa cámara/YOLO | Cómo interpreta |
|---|---|---|
| A | En el intervalo periódico congelado, si está disponible | Reglas. |
| B | Ante los disparadores simples congelados | Reglas. |
| C | Cuando falta evidencia visual necesaria o debe renovarse para el objetivo | Reglas. |
| D | Con la misma política de adquisición que C | Reglas para respuestas directas; Gemma para tipos de interpretación habilitados. |

Cuando una variante no tiene evidencia vigente para contestar, reconoce esa limitación; no se le añade una captura oculta para mejorar su resultado. Las cuatro registran las mismas clases de eventos ambientales, fallos y preguntas aunque no utilicen visión de igual manera.

El contraste A–B–C informa principalmente sobre adquisición. C–D con snapshots idénticos informa sobre interpretación. No se espera una diferencia entre las cuatro en cada escenario.

## 4. Cuándo activar componentes

| Condición | Actualizar contexto / respuesta | Cámara en C/D | Gemma en D |
|---|---|---|---|
| Lectura ambiental normal o fluctuación menor | Guardar dato y frescura; no abrir un episodio costoso | No por esa lectura | No. |
| Radar cambia y solo se necesita presencia | Registrar transición y responder por reglas | No por defecto | No. |
| Se necesita conteo y falta uno válido | Abrir necesidad de conteo | Sí, si puede aportar y cabe en presupuesto | No para decir el número. |
| El objetivo exige conteo vigente y vence su TTL | Programar renovación, incluso si radar no cambió | Sí, con límites | No por el mero vencimiento. |
| Variación ambiental supera criterio y persistencia | Abrir episodio y reunir historial/calidad | Solo si existe una pregunta visual pertinente | Sí si su tipo está habilitado para interpretación y hay evidencia mínima; no automáticamente por cualquier salto. |
| Fuente ausente o datos antiguos | Marcar indisponibilidad/antigüedad, responder o renovar según objetivo | Solo si la modalidad visual puede responder lo pendiente | No para inventar lo que falta. |
| Radar/visión discrepan en tiempo y región comparables | Conservar discrepancia y evaluar corroboración | Renovar solo si aporta | Puede explicar límites si el perfil lo requiere. |

El radar no es el único origen de episodios. Temperatura, indicadores ENS160, disponibilidad, TTL y contradicciones también alimentan la FSM. Una cámara no observa concentración de gas: ausencia de disturbios visibles no permite concluir ausencia de riesgo.

## 5. Ejemplo guiado de un cambio ambiental

1. El investigador inicia una ejecución con perfil y variante fijados. Recursos se registran automáticamente; W se introducen según la cadencia.
2. El guion produce una variación segura/registrada o activa un fixture identificado. La hora real se anota, sin revelar al SLM la respuesta esperada.
3. Las reglas detectan si cumple magnitud, persistencia y calidad. Si no, solo actualizan datos; el escenario no obliga a fabricar una detección.
4. La FSM reúne el snapshot: antes/ahora, tiempos, calidad, presencia y cualquier evidencia visual ya disponible, con sus límites.
5. A/B/C emiten su resultado determinista. D puede emitir una interpretación breve de esos mismos hechos si la guarda de interpretación está satisfecha. La cámara conserva la política correspondiente a cada variante.
6. El resultado puede decir «variación observada, causa desconocida, pendiente comprobar persistencia». No «alguien prueba butano y no pasa nada» sin respaldo.
7. La FSM agenda la siguiente comprobación permitida. Una publicación nueva o temporizador provoca otra evaluación; no se ejecuta un bucle generativo esperando datos.
8. Si el indicador retorna al rango de referencia, se registra ese retorno; no una certificación de seguridad. Si persiste o no hay datos hasta vencer el presupuesto, el episodio queda con limitación explícita.

## 6. Qué significa pendiente, resuelto o no respondible

Cada ciclo operativo termina en REPORT, pero el fenómeno puede requerir seguimiento. Una salida conserva `followup_status`, `next_check_at` si procede y referencias a evidencia. La comprobación posterior es otro episodio, enlazado mediante `followup_of_episode_id`; así se conserva el límite de llamadas por ciclo y se evita una espera bloqueante.

| Estado contextual de salida | Significado |
|---|---|
| `resolved_by_evidence` | La pregunta definida se respondió con evidencia suficiente, sin afirmar una causa más amplia. |
| `pending_followup` | Hay una comprobación concreta programada, con fuente, condición de cierre y plazo. |
| `insufficient_evidence` | No es posible responder con las fuentes/alcance disponibles; no hay dato inventado. |
| `expired` | Se agotó plazo o presupuesto de corroboración sin resolver la pregunta. |

Definir máximo de seguimientos por tipo de episodio en piloto. Alcanzarlo cierra como no resuelto/expirado según corresponda, no como normal. La nueva comprobación no obliga a llamar de nuevo a Gemma: puede bastar una regla. En C–D de evidencia congelada, no se adquieren datos extra; se evalúa la petición de corroboración como salida.

## 7. Lo que hace el investigador durante una ejecución

1. Seleccionar espacio, bloque, variante y guion; verificar fuentes y condiciones iniciales.
2. Pulsar inicio tras la fase de estabilización fijada.
3. Seguir las indicaciones físicas del guion. Preguntas y fallos lógicos se programan automáticamente.
4. Registrar tiempos reales y referencia de presencia/conteo, idealmente con otro observador que no vea las predicciones.
5. Introducir W observados, con su tiempo y cualquier retraso de transcripción.
6. Finalizar, guardar y comprobar que los archivos existen y cubren la sesión. No modificar parámetros tras ver una respuesta mala durante la prueba final.
7. Restablecer fuentes/escena y repetir el guion con la siguiente variante del orden predefinido.

Completar A–D forma un bloque. El piloto sirve para corregir guion y software. El ensayo final sirve para evaluar con parámetros congelados. La propuesta sigue siendo cuatro bloques piloto y veinte finales, revisables antes de iniciar los finales según variabilidad y viabilidad.

## 8. Qué queda al terminar y cómo se evalúa

El producto operacional es un estado contextual, una respuesta o abstención y, cuando corresponde, un seguimiento programado. En el alcance actual no hay actuadores físicos. Su utilidad es monitorear y comunicar qué se conoce y qué necesita corroborarse.

Los CSV conservan entradas, decisiones, acciones, respuestas, seguimientos, fallos, recursos y potencia. Las etiquetas humanas permiten evaluar detecciones, conteo, omisiones y latencia; la rúbrica puntúa si la interpretación está respaldada. Una conclusión convincente pero falsa cuenta como error.

Así se puede argumentar si C reduce trabajo frente a A/B, si pierde eventos, si D mejora respuestas frente a C y con qué costo. Descripción directa de imágenes y adquisición guiada por propuestas del SLM son variantes separadas si modifican la evidencia disponible.
