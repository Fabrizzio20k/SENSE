# Revisión visual del rediseño v2

## Capturas de referencia anteriores

Las cuatro imágenes iniciales aportadas por el usuario están en `before/preparacion.png`, `before/medicion.png`, `before/experimentacion.png` y `before/replay.png`. Las capturas de ajustes posteriores están en `before/medicion-feedback.png`, `before/medicion-espaciado-feedback.png`, `before/medicion-botones-feedback.png`, `before/grafo-feedback.png`, `before/grafo-interaccion-feedback.png`, `before/sidebar-feedback.png`, `before/experimentacion-guion-feedback.png`, `before/preparacion-botones-feedback.png`, `before/replay-feedback-1.png` a `before/replay-feedback-3.png` y `before/replay-player-feedback.png`, `before/replay-events-feedback.png`, `before/replay-intro-feedback.png`, `before/replay-hover-feedback.png`, `before/replay-controles-zip-feedback.png`. No se alteraron.

## Verificación ejecutada

- `/offline`: probado por la suite Node sin llamadas `fetch` ni SSE reales; escenas de carga, ejecución, pendientes, datos incompletos, fallas y Replay.
- Estado, formularios y contratos: pruebas de ceros, Q2, W, horas, pendientes, acción aceptada y registro posterior.
- Replay: 14 métricas en cuatro grupos; categorías de la leyenda iguales a las de los marcadores; huecos y resultados tardíos.
- Accesibilidad de código: foco visible, pestañas con flechas/Home/End, etiquetas de controles, movimiento reducido y botón de pausa.
- Temas: paletas claro y oscuro declaradas; todos los SVG referenciados en CSS existen para ambos temas.
- Ajuste posterior: cada lectura muestra su icono v2; metadatos completos bajo “Detalles”; sin celdas grises vacías. El grafo SVG offline permite arrastrar, ampliar y centrar, y destaca la última transición.
- Inspección posterior: nodos seleccionables con clic/teclado y selector accesible; iconos animados solo en el estado activo, pulso breve de transición nueva; movimiento reducido y pausa manual respetados.
- Replay: las 14 métricas muestran iconos del mismo paquete, se eliminaron los fondos de celdas sin datos y el archivo cargado ocupa menos altura.
- Replay, ajuste visual posterior: encabezado más legible con icono v2; reproductor con progreso, escala y marcas por categoría; lista con iconos y evento del cursor resaltado. Se conservan controles, filtros y detalle original.
- Ajuste posterior de jerarquía: iconos del reproductor visibles al pasar el cursor en ambos temas; separación antes de Lecturas actuales; numerales de sección sin marco; utilidades del lateral con iconos y contraste; guion, reglas y preguntas experimentales desplegables con línea de tiempo visual.
- Ajuste de controles: botones secundarios neutrales con tamaño y borde comunes, una acción principal por contexto; anterior/siguiente quedan como controles de icono con nombre accesible; carga ZIP y resumen distribuidos en una franja compacta.
- Pruebas: `node --test tests/*.test.cjs` y `.venv/bin/python -m unittest discover -s tests -v`.

## Límite de captura

No se generaron imágenes “después”: Computer Use rechazó el acceso a Brave; el navegador integrado no está disponible; Brave headless terminó con código 134. Por ello quedan sin comprobación visual directa la composición exacta en ambos temas, al 200 % de zoom y durante desconexión. No se sustituyeron por un mockup.

Para completar las capturas en una sesión con navegador disponible, ejecutar `python serve_offline.py`, abrir `/offline` y fotografiar a 1440×900 y 390×844: Preparación lista, Medición en curso, pendientes, Experimentación S1, Replay cargado, claro/oscuro y zoom 200 %. Guardar las imágenes en `after/` para compararlas con `before/`.
