# Revisión de las capturas actuales de SENSE
Fecha: 30 de octubre de 2026.
Alcance: las 13 capturas del usuario y el contexto funcional anterior. No se recibió el repositorio del frontend en este chat. Los hallazgos son visuales o aparentes, no defectos de backend comprobados.

## Mejoras concretas
1. **Reloj con icono equivocado.** En Medición se usa el símbolo de potencia para el tiempo. El nuevo timer corrige la asociación. power queda para W.
2. **Gemma texto e imagen indistinguibles.** Preparación necesita dos variantes del mismo motivo, sin perder la identidad de Gemma.
3. **Lecturas con posiciones irregulares.** Humedad y otras tarjetas no comparten la alineación de título/valor/estado. Organizar en grupos Presencia/visión y Ambiente.
4. **Celdas de relleno grises.** Se ven espacios artificiales al final de Lecturas y Q7. Quitar únicamente esos rellenos sin contenido. No quitar métricas para lograr simetría.
5. **Tarjetas demasiado altas.** Las respuestas Q1–Q7 ocupan varios desplazamientos. Usar resumen visible y detalle completo accesible para cada pregunta.
6. **FSM dominante y demasiado dispersa.** Mantener el diagrama completo en inspección. En operación mostrar estado actual, última transición y tareas separadas. Las conexiones reales se conservan.
7. **Texto de estado aparentemente inconsistente.** Una captura muestra cronómetro avanzando y “Esperando inicio”. Verificar el enlace al snapshot. WAIT no significa ejecución no iniciada.
8. **Botón deshabilitado con mucho verde.** Cuando no hay pendientes, el estado vacío debe ser neutro. El contador global puede corresponder a otra ejecución o a un registro histórico y debe conservar su alcance.
9. **Sandbox vacío muy alto.** Altura inicial moderada y crecimiento por contenido. Mantener toda la conversación y las acciones de foto/modelos.
10. **Replay requiere demasiada exploración vertical.** Agrupar sus 14 métricas, workers, respuestas, eventos y JSON. Los detalles permanecen accesibles.
11. **Barra sticky de Replay alta.** Compactar y revisar que no cubra foco ni encabezados. Su altura y scroll-margin deben coordinarse.
12. **Leyenda de eventos por comprobar.** Los marcadores parecen muy similares pese a la leyenda de colores. Usar el mismo mapa de tipos para leyenda y marcas, más forma o pista de fila.
13. **Tipografía pequeña en navegación y metadatos.** Mantener cuerpo legible y adaptar ancho de sidebar sin aumentar el tamaño del cartel de sección.
14. **Datos científicos sensibles a una simplificación excesiva.** Preservar edad, región, fuente, limitaciones, estados, evidencia histórica, cero válido y el cegamiento de Q2.

## Color
La base hueso/grafito y el verde marciano ya forman una dirección coherente. Se propone conservarla y ajustar jerarquía: selección/acción primaria en verde vivo, operación normal neutra, evidencia válida con etiqueta discreta, aviso en ámbar y error en rojo sobrio. No usar un solo verde para selección, pendiente, histórico y completado.

## Iconos nuevos
36 incorporaciones para métricas, modalidades de Gemma, estados de evidencia, paneles, registro humano y Replay. 6 variantes de actividad adicionales.
No es necesario usar toda la biblioteca simultáneamente. Un símbolo por grupo o acción reconocible es suficiente. Los valores siguen siendo texto.

## Orden recomendado
Preparación: comprobación compacta, modelos diferenciados, sandbox y telemetría.
Medición: sesión, lecturas, acciones del observador y respuestas. Inspección técnica al lado o bajo demanda.
Experimentación: configuración/condiciones iniciales antes de iniciar. Durante la sesión, Ahora/siguiente paso y pendientes.
Replay: reproductor compacto, grupos de lecturas, respuestas/tareas/humano y eventos con detalle seleccionado.

## Comprobación
La implementación debe inventariar cada dato/acción y mapearlo a su ubicación nueva. La aceptación exige acceso al 100 % de la información anterior, no una pantalla con menos contenido funcional.
Verificar con las escenas offline y el archivo real de Replay. No modificar duración ni muestras para que coincidan con un diseño.

## Referencia
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
La revisión usa sus criterios de foco, etiquetas, controles, movimiento reducido y acciones destructivas. La conformidad del código debe comprobarse en el repositorio real.

