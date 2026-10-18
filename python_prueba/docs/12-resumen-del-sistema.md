# 12. Explicación directa del sistema final

## Qué se va a construir

Un programa Python en la Raspberry Pi y una página para observarlo y hacer experimentos. Los sensores que ya publican en MQTT siguen funcionando como ahora. El programa reúne sus datos y decide cuándo hace falta usar cámara, YOLO o Gemma. Todo el cálculo permanece local.

El modelo no trabaja en cada lectura: una pregunta de temperatura o presencia puede resolverse con datos y reglas. Si se necesita contar personas, se usa YOLO. Si se necesita interpretar una situación, se consulta Gemma con los datos necesarios. Para una pregunta semántica sobre una foto puede usarse Gemma multimodal en una ruta separada. Thinking permanece desactivado en todos los casos.

## Qué se verá en la página

Verás en vivo la FSM, el dato que está usando, la herramienta que eligió y la razón: «radar suficiente», «conteo vencido», «cámara no disponible» o «evidencia insuficiente». Verás CPU, RAM, temperatura de la Pi y los puntos de W que introduzcas leyendo el vatímetro. Son decisiones y registros observables, no una transcripción de pensamiento interno.

Podrás desactivar lógicamente un sensor o cámara mientras se ejecuta una prueba. El software dejará de usar esa fuente, conservará lo histórico como histórico y tendrá que responder con lo disponible o reconocer que no sabe. Al restaurar, esperará un dato nuevo. También podrás simular silencio para comprobar que detecta que los datos envejecen.

Eso simula falta de información; no apaga físicamente el sensor ni demuestra ahorro por cortar su alimentación. Para medir ese efecto haría falta otro ensayo físico.

## Un ejemplo completo

1. Hay radar y ambiente vigentes: la consulta de presencia se responde sin cámara ni Gemma.
2. Preguntas cuántas personas hay: si no existe conteo visual vigente, captura y ejecuta YOLO.
3. Desactivas la cámara desde la página: una nueva consulta de conteo debe declarar que no puede renovarlo, no inventar cero.
4. Pides interpretar datos de ambiente y presencia: Gemma recibe un snapshot con tiempos, fuentes y límites, si la política considera que aporta algo.
5. Registras 7,4 W del vatímetro en el instante observado; el gráfico añade ese punto y la estimación de energía se actualiza con los intervalos cubiertos.
6. Descargas los CSV de la ejecución para estudiar decisiones, latencia, aciertos, fallos y recursos.

La página consume streaming SSE para recibir cada novedad; la Pi conserva el registro incluso si cierras la página. Los controles son peticiones HTTP registradas, con confirmación de su efecto.

## Cómo se probará

La [guía de medición paso a paso](13-guia-de-medicion.md) concreta las condiciones de activación y el trabajo del investigador. A–D son configuraciones del programa; los escenarios físicos se repiten con cada una. A/B/C pueden usar YOLO, pero interpretan con reglas. D interpreta con Gemma solo en tipos de episodio habilitados y con evidencia suficiente.

Se comparan A (visión periódica), B (disparo simple), C (adaptación con reglas) y D (misma adaptación con interpretación Gemma cuando procede). Cada variante atraviesa el mismo guion y recibe las mismas preguntas; en una prueba adicional reglas y Gemma reciben exactamente los mismos snapshots.

El guion cubre ambiente estable, ingreso/salida, personas inmóviles, presencia fuera de radar pero dentro de cámara, cambios ambientales, radar desactivado, fallo de un sensor ambiental, cámara no disponible, dato congelado y evidencia contradictoria.

Propuesta inicial: cuatro bloques piloto separados de los resultados y después veinte bloques finales, diez en aula y diez en laboratorio. Cada bloque prueba las cuatro variantes: **80 ejecuciones finales**. Con veinte minutos puntuados por ejecución son **26 h 40 min**, más preparación y pausas. Cada escenario tendría veinte presentaciones por variante entre los dos espacios, si todas son evaluables. El piloto puede exigir más tiempo o bloques antes de congelar el protocolo.

No se puede garantizar que ese número produzca significancia estadística: sirve como plan concreto de trabajo, que se ajusta a variabilidad y diferencia mínima relevante. Los puntos tomados cada segundo no cuentan como experimentos nuevos.

## Qué se obtendrá al terminar

Una interfaz para observar el sistema, controles repetibles de fallos y un paquete de datos por prueba: lecturas, decisiones, acciones, CPU/RAM, W introducidos, respuestas y etiquetas humanas. Con esos datos podrás argumentar cuándo evita trabajo, cuándo mantiene la calidad, cuándo necesita visión, cuánto cuesta Gemma y qué pasa cuando faltan fuentes.

La energía calculada desde W periódicos será una estimación con cobertura conocida; no mostrará picos que no hayas observado. Los métodos y CSV están en [10](10-controles-y-csv.md) y el plan de ensayos con sus límites en [11](11-escenarios-y-repeticiones.md).

Un cambio ambiental no implica cámara ni SLM automáticos. Puede abrir seguimiento si cumple criterios definidos, producir una respuesta parcial y programar nuevas lecturas. El sistema monitorea y comunica; no identifica automáticamente un gas, certifica seguridad ni acciona dispositivos físicos.
