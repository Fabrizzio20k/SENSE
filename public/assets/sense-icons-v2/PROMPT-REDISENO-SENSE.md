# Encargo para Codex: reorganizar SENSE sin perder información
Trabaja sobre la aplicación existente, no sobre una maqueta nueva. Usa las capturas adjuntas como evidencia de la UI actual y el paquete sense-icons-v2 como biblioteca de recursos.

## Resultado esperado
Mejorar la jerarquía visual, reducir scroll innecesario y facilitar medición, experimentación y análisis de Replay. Conservar todos los datos, controles, reglas y posibilidades de inspección. Reorganizar información no equivale a eliminarla.
Implementa el cambio en el repositorio disponible. No te quedes en una propuesta. Si el repositorio no está disponible, indica esa dependencia en lugar de inventar archivos o declarar una implementación.

## Inspección y límites
1. Lee AGENTS.md, el contexto de SENSE y el código actual de public/ antes de editar. Revisa index.html, panel.css, measurement.css, replay.css, theme.js, api.js, app.js, measurement.js, experiment.js, offline.js, replay-data.js y replay.js, o sus equivalentes reales.
2. Haz un inventario de todas las lecturas, atributos, estados, formularios, acciones, tablas y detalles existentes. Al terminar, entrega una matriz breve “elemento anterior → ubicación nueva”. Esta matriz debe demostrar que no se perdió información.
3. Reutiliza el transporte y los contratos reales. No introduzcas framework, dependencias de animación ni build innecesarios.
4. Conserva los IDs o actualiza coordinadamente sus referencias y pruebas. No dupliques #measurement-workspace. Medición y Experimentación siguen compartiendo el workspace según la implementación existente.
5. No cambies políticas A–F, FSM, guiones S1–S3, backend, endpoints, almacenamiento, TTL ni semántica para acomodar la presentación.
6. Los números de las capturas son ejemplos de offline, no fixtures obligatorios para la UI nueva.

## Dirección visual
Mantén la identidad actual: fondo hueso, grafito, superficies claras, líneas finas y verde marciano. No es necesario cambiar la marca ni saturar la pantalla de color.
Tokens propuestos:
- Fondo #F3F0E9, superficie #FAF8F2.
- Texto #24251F, secundario #5E6056, borde #C9C7BD.
- Verde marciano #C9F75A, selección suave #EAF5CE.
- Aviso: texto #825B16 sobre fondo tenue #F7EED8.
- Error: texto #A43434 sobre fondo tenue #F9E5E2.
- Tema oscuro: fondo #1C1D19, superficie #24251F, texto #EAE4D3, secundario #BBB9AA, borde #55544A.
Verifica contraste real. El verde claro lleva texto grafito. No uses texto verde claro sobre hueso.
El verde vivo destaca selección y una acción primaria. Los botones deshabilitados usan tonos neutros y una explicación si hace falta. “Finalizar” es secundario, no un botón verde principal.
Tipografía: cuerpo 16 px, metadatos normalmente 12–13 px, títulos 28–36 px, cifras tabulares. Pixel art solo en iconos y detalles.
Reduce el código de barras y número de sección. La cabecera operativa no necesita proporciones de cartel.
Espaciado de 8, 12, 16, 24 y 32 px. Barra lateral aproximadamente 184–208 px con etiquetas legibles. Contenedor fluido que aproveche el ancho, con límite de lectura razonable. Panel lateral operativo de unos 288–320 px cuando haya espacio.
Agrupa con espacio y separadores, no una tarjeta dentro de otra para cada dato. No añadas celdas grises de relleno para completar una cuadrícula. Corrige tarjetas con títulos desalineados y alturas excesivas, especialmente Humedad y la última celda vacía.
Evita texto de diagnóstico del backend en el flujo habitual. Su detalle se conserva en la zona avanzada.

## Biblioteca de iconos
Copia el paquete completo a una ubicación estable, por ejemplo public/assets/sense-icons-v2, adaptándola al proyecto.
Lee manifest.json, UI-MAP.json y LEEME.md. Usa SVG inline mediante web/sense-icons.js y web/sense-icons.css, o SVG individuales. Mantén juntos atlas y CSS si eliges sprites PNG.
Conserva los nombres existentes. Usa:
- timer para tiempo de ejecución. power solo para potencia W.
- sht40, ens160, radar, camera como identidad de las fuentes físicas.
- temperature, humidity, aqi, tvoc, eco2, distance como métricas cuando facilite escanear.
- gemma-text y gemma-image para distinguir los modelos/tareas de texto e imagen.
- presence, yolo, changes, evidence, context e image junto a los grupos correspondientes.
- pending, observer, event, quality, history, health, diagnostic y telemetry para los encabezados y acciones apropiados.
- play, pause, previous, next, upload, filter y export en Replay.
Un icono de 20–24 px suele bastar en controles. No coloques los 64 iconos por el mero hecho de tenerlos. Mantén texto en acciones importantes y nombres accesibles en botones de solo icono.
No sustituyas todos los símbolos por emojis, librerías genéricas o imágenes recortadas.

## Animación
Todo inicia estático. Activa una animación únicamente desde un estado real ya disponible. No inventes campos ni generes inferencias para producir movimiento.
- gemma-text/gemma-image: solo mientras la tarea correspondiente esté ejecutándose. Si no hay modalidad explícita, usa gemma genérico.
- yolo: durante tarea real de detección. camera: durante captura real.
- tasks: actividad o cola confirmada. telemetry: recepción reciente dentro del umbral de transporte existente, no un temporizador que finja paquetes.
- refresh: solicitud de reevaluación pendiente, sin asumir que llama a Gemma o cámara.
- upload: solo mientras se lee/valida el ZIP local. Nunca implica subirlo a un servidor.
- FSM: solo el estado actual puede mostrar actividad. Un resultado o una transición pasada no debe seguir animándose.
- timer, lecturas, pendientes y errores permanecen estáticos normalmente. No hacer parpadear la pantalla ni animar cada cambio numérico.
Como regla visual, mantener una o dos animaciones visibles como máximo, salvo que otra tarea deba comunicar actividad relevante. No ocultar que existen varias tareas reales.
Respeta prefers-reduced-motion, añade una opción persistente para detener movimiento no esencial y suspende animaciones fuera de vista cuando resulte sencillo. El helper .setActive(false) vuelve al reposo.
Prefiere SVG/CSS. Los GIF quedan como alternativa de compatibilidad y requieren fallback estático para movimiento reducido.
Un ciclo animado no es un porcentaje ni un tiempo real.

## 01 Preparación
Orden:
1. Encabezado compacto con entorno real/offline y conexión.
2. Resumen del sistema: CPU, memoria en porcentaje y MB, y los demás recursos actuales.
3. Comprobación de sensores y modelos en filas/tarjetas compactas.
4. Sandbox.
5. Telemetría cruda y diagnóstico bajo demanda.
Conserva MQTT, SHT40 (temperatura y humedad), ENS160 (AQI, TVOC y eCO₂ cuando estén presentes), presencia/distancia/cobertura y sus estados.
Conserva los tres grupos de modelos que se ven: YOLO/NCNN, Gemma texto y Gemma imagen. No representes ambos Gemma como una única preparación si sus estados son distintos.
El sandbox vacío puede empezar con una altura moderada y crecer con mensajes/foto/resultados. Conserva entrada de texto, foto, envío y acciones asociadas.
La telemetría JSON sigue accesible y copiable, con altura controlada. No ocupa permanentemente una sección enorme.
Los controles de demo “Escena”, “Avanzar 1 min” y “Reiniciar demo” siguen disponibles en offline, agrupados en una barra discreta o desplegable. No aparecen como control de hardware real.

## 02 Medición y pruebas
Antes de iniciar: selector A–F, disponibilidad real, acción Comenzar y estado.
Durante una ejecución: resumen compacto y persistente con modo, estado, transcurrido/restante y pendientes si existen. Finalizar pide confirmación antes del cierre anticipado.
No uses el icono de vatímetro en el reloj.
Agrupa las lecturas en:
- Presencia y visión: radar, distancia/zona/cobertura, conteo YOLO.
- Ambiente: temperatura, humedad, AQI, TVOC y eCO₂ estimado.
Conserva cada lectura individual con valor, unidad, fuente, edad, región y estado. Agrupar no es fusionar valores ni quitar metadatos. Evita repetir el mismo bloque de fuente muchas veces si existe un encabezado común y el detalle individual sigue disponible.
Respeta cero, desconocido, vencido, conflicto, no disponible y error.
La UI puede tener vista operativa y vista de inspección en el mismo workspace. La operativa muestra lecturas, respuestas relevantes y acciones del observador. La inspección abre FSM, tareas, salud y diagnóstico.
Conserva las siete respuestas Q1–Q7. Hazlas filas o bloques compactos con pregunta, respuesta, estado y evaluación visibles. El texto completo, fuentes, limitaciones, faltantes, evidencia y contrato se despliegan sin perder contenido. No recortes silenciosamente respuestas o limitaciones.
La advertencia global de simulación permanece visible. Evita repetir párrafos idénticos en cada tarjeta cuando el detalle conserva la procedencia exacta.
Conserva reevaluación manual por pregunta y su aclaración: no fuerza captura ni llamada a Gemma.
Conserva interpretaciones recientes con origen, validación, momentos y evidencia histórica. Las salidas tardías no se vuelven actuales.
Conserva historial, CSV, ZIP, NDJSON y completar observaciones históricas. No ocultes descargas detrás de un control sin nombre.
Recursos CPU, RAM sistema, RAM SENSE y temperatura Pi permanecen accesibles en una franja compacta o detalle. No son el bloque principal de atención en una medición.

## Máquina de estados
Conserva WAIT, ACQUIRE, ASSESS, VISION, INTERPRET, REPORT y DEGRADED y todas las transiciones reales.
La disposición puede cambiar para reducir cruces y mejorar lectura. No cambies las conexiones para embellecer el grafo.
Un único estado actual destacado. Distingue nodos visitados históricamente y nodos inactivos. “Pendiente” no debe insinuar que todos los estados se ejecutarán obligatoriamente.
WAIT es un estado de la FSM, no necesariamente una sesión sin iniciar. Si el contador avanza y el texto dice “Esperando inicio”, revisa su enlace al snapshot real.
DEGRADED comunica evidencia parcial y continuidad cuando corresponde, no finalización.
Muestra tareas activas/encoladas aparte de la FSM. Gemma puede seguir en ejecución cuando la FSM volvió a WAIT.
Conserva última transición y traza completa en detalle. Si el grafo externo falla, mantener lista HTML legible.

## Observaciones humanas
Panel contextual estable con cola, motivo, hora del evento y campos requeridos.
Mantén el contador global cuando se navega. Si pertenece a otra ejecución o a un histórico, identifica su alcance. No lo pongas a cero solo por cambiar de sección.
Si no hay pendientes, muestra un estado neutro. No destaques con verde un botón deshabilitado.
Conserva registrar evento real, guardar, repetir anterior explícitamente, no observado con motivo, dejar pendiente y completar históricos.
Hora del evento del backend y hora de lectura humana son distintas. Muestra solo los campos que la solicitud exige.
Preserva el borrador mientras llega SSE y evita robar foco por nuevas solicitudes.
No confundas número de solicitudes del observador con número de respuestas Q pendientes.

## 03 Experimentación
Conserva escenario S1–S3, modo A–F y repetición 1–3, guion completo, reglas y preguntas experimentales.
Si ya hay una ejecución activa y los selectores deben estar bloqueados, explica el motivo con un enlace para continuarla. No habilites una segunda ejecución para evitar la apariencia de deshabilitado.
Antes de iniciar, pedir las condiciones iniciales existentes. El reloj empieza al guardarlas conforme al backend.
Durante la sesión, mostrar Ahora y siguiente paso derivados del escenario y elapsed_s, con tiempos orientativos. Registrar la acción cuando ocurre realmente.
Conserva las reglas específicas de B, D y demás modos exactamente como las define el proyecto.
Mantén oculto Q2/estimación YOLO mientras esté pendiente visible_people en una sesión guiada, incluidos tooltips y textos accesibles que puedan revelar el valor. Observaciones humanas y política permanecen separadas.

## 04 Replay
Conserva importación ZIP local, carga de ejemplo, reproducción/pausa, velocidad, anterior/siguiente hito, cursor, hora, filtros y lista completa de eventos.
Compacta la barra de reproducción. Si es sticky, no debe tapar títulos, foco, respuestas ni paneles al desplazarse. Define scroll-margin y comprueba zoom.
Agrupa los datos del cursor en Ambiente, Presencia/visión, Recursos y Tareas. Conserva temperatura, humedad, AQI, eCO₂, TVOC, presencia, conteo YOLO, distancia, CPU, RAM sistema, RAM SENSE, temperatura Pi y workers YOLO/Gemma.
Mantén estado y edad al cursor por lectura, respuestas guardadas hasta ese instante, tareas/resultados Gemma, observaciones humanas, muestra original y solicitudes originales.
No elimines filas para que la cuadrícula encaje. Un grupo con menos elementos no necesita una celda gris vacía.
No impongas duración exacta de 30:00 sobre un archivo que muestra 30:05. Distingue duración objetivo, duración real y extensión de la traza según los campos reales.
Conserva huecos de muestras y resultados tardíos. Replay no vuelve a ejecutar modelos ni sube archivos.
La lista de eventos puede usar paginación o virtualización, conservando acceso a todos los registros. Mantén el seleccionado visible sin saltos de foco.
El detalle del evento muestra resumen legible y JSON original bajo demanda. No abrir varios grandes paneles de JSON por defecto.
Comprueba que la leyenda y los marcadores comparten el mismo mapa de tipos. En las capturas se perciben muchos marcadores con un color similar pese a la leyenda de tareas/fallas/observaciones. Usa forma o pista de fila además de color y conserva el tipo original del evento.

## Reglas científicas y de transporte
No calcular Wh a partir de W ni atribuir W exclusivamente a Gemma. eCO₂ sigue siendo estimado.
No convertir null en cero ni presentar presencia limitada como ocupación global.
Auto/Manual es intervención del operador, no ground truth. Fallas F son simulación de software cuando así las define el sistema.
No deducir causalidad de coincidencia temporal.
record_complete y duration_completed son distintos.
Un 202 confirma aceptación, no finalización. El resultado definitivo llega por el canal de estado.
En desconexión, mostrar última información recibida con antigüedad y bloquear nuevas acciones conforme al contrato. El backend puede continuar.
No guardar fotografías ni inventar una galería histórica.
Mantén las validaciones y los mensajes de error con el siguiente paso.

## Accesibilidad, actualización y comprobación
- Botones reales para acciones, controles etiquetados y enlaces para navegación.
- Foco visible, controles de al menos 44 px y funcionamiento por teclado.
- Evitar movimientos de layout y pérdida de foco por SSE cada segundo.
- Colores semánticos con texto e icono, no solo color.
- Preferencia claro/oscuro persistente y movimiento reducido.
- Mantener móvil y revisar 1280, 1440 y 1920 px, además de zoom 200 %. Los puntos de corte se adaptan al contenido real.
- No depender de hover para datos imprescindibles ni truncar información sin acceso al texto completo.
- Revisa /offline con preparación, sin iniciar, en curso, pendientes, cierre, F/falla, datos incompletos y desconexión. Revisa Replay con un hueco y una salida tardía.
- Ejecuta los checks pertinentes existentes. Si corresponden al repositorio: .venv/bin/python -m unittest discover -s tests -v y node --test tests/*.test.cjs.
- Si una prueba exige hardware no disponible, informa esa limitación y valida con offline sin inventar resultados.

## Entrega
Implementa los cambios autorizados. Entrega resumen de mejoras, matriz de conservación de datos/acciones, capturas antes/después comparables y verificación realizada. No publiques ni despliegues sin una instrucción adicional. No declares que la UI es más rápida sin una prueba de uso.

## Referencia de revisión
Las capturas y el contexto SENSE del usuario son las fuentes del comportamiento. Para accesibilidad e interacción se consultó https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md . La evaluación de capturas no sustituye la inspección del código.

