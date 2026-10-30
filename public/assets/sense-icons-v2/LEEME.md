# SENSE · Iconos y sprites v2

64 iconos originales y 18 animaciones opcionales, dibujados sobre retícula de 24 × 24 px. Familia vectorial recreada a partir de la muestra artística de SENSE. Los archivos están listos para integración, sin dependencias en el navegador.

## Qué abrir primero
Abre `preview/index.html`. Permite activar cada animación, cambiar el tamaño y probar el tema oscuro. Funciona con los archivos locales y sin conexión a internet.

## Archivos
- `svg/light/` y `svg/dark/`: iconos estáticos transparentes, grafito y marfil.
- `animated-svg/light/` y `animated-svg/dark/`: SVG animados autónomos. Respetan movimiento reducido.
- `png/light/` y `png/dark/`: PNG transparentes a 24, 48 y 96 px.
- `sprites/static-light.png` y `static-dark.png`: atlas de 8 columnas × 8 filas, celdas de 48 × 48 px.
- `sprites/animated/`: una tira horizontal de 8 fotogramas por icono, de 384 × 48 px.
- `gif/`: GIF transparentes de los 18 iconos con actividad. Son una alternativa de compatibilidad, no la opción principal de accesibilidad.
- `sprite.svg`: símbolos SVG estáticos con IDs `sense-radar`, `sense-yolo`, etc.
- `web/`: estilos, reproductor SVG y variante CSS para sprites PNG.
- `manifest.json`: nombres, etiquetas, rutas, posiciones y duración.
- `icon-definitions.mjs`: fuente editable de todos los dibujos y fotogramas.

## Opción recomendada: SVG inline controlado por el estado
Copiar `web/` y conservar las rutas relativas. No hace falta framework.

```html
<link rel="stylesheet" href="/assets/sense-icons/web/sense-icons.css">
<script src="/assets/sense-icons/web/sense-icons.js"></script>
<span id="radar-icon"></span>
<script>
  const radar = SenseIcons.create({
    name: 'radar', size: 24,
    label: 'Radar recibiendo telemetría', active: false
  });
  document.getElementById('radar-icon').append(radar.element);
  // Activar solo desde un estado real recibido por la aplicación.
  radar.setActive(true);
  // Detener y volver al fotograma de reposo.
  radar.setActive(false);
</script>
```

El SVG inline hereda `color`. Así funciona en claro y oscuro con el mismo recurso:

```css
.sensor-icon { color: #24251F; --sense-accent: #C9F75A; }
[data-theme="dark"] .sensor-icon { color: #EAE4D3; }
```

También se puede usar el módulo `web/sense-icons.mjs` desde un servidor web. La demostración local usa la variante clásica para funcionar al abrir el archivo.

## Alternativa rápida: archivo SVG
```html
<img src="/assets/sense-icons/svg/light/sht40.svg"
     width="24" height="24" alt="SHT40">
```

Un SVG dentro de `<img>` usa el color de su propio archivo. Para recolorearlo con CSS del padre, usar la opción inline. Los archivos de `animated-svg/` empiezan a animarse al mostrarse. Se puede cambiar entre la ruta estática y animada según actividad.

## Alternativa con sprites PNG
```html
<link rel="stylesheet" href="/assets/sense-icons/web/sense-sprites.css">
<span class="sense-sprite is-animated is-active"
      data-icon="gemma" data-theme="light"
      role="img" aria-label="Gemma en ejecución"
      style="--sense-size:24px"></span>
```

Quitar `is-active` detiene la reproducción y vuelve al primer fotograma. Quitar `is-animated` muestra el atlas estático. Mantener juntos `web/` y `sprites/` o actualizar las URLs del CSS. Los tamaños 24, 48 y 96 conservan una escala entera del píxel.

## Nombres
Fuentes: `sht40`, `ens160`, `radar`, `camera`, `power`.
Modelos: `yolo`, `gemma`.
Máquina: `wait`, `acquire`, `assess`, `vision`, `interpret`, `report`, `degraded`.
Navegación: `preparation`, `measurement`, `experiment`, `replay`.
Acciones/estados: `observe`, `save`, `export`, `lock`, `connection`.
Recursos/lecturas: `pi`, `cpu`, `memory`, `temperature`, `humidity`.

## Animación y semántica
- Los 18 iconos con actividad tienen 8 fotogramas. Duración habitual 1600 ms, `degraded` 2400 ms.
- Radar: recorrido discreto de ondas. Cámara: breve obturación. YOLO: ajuste del marco. Gemma: secuencia de nodos. WAIT: reloj de espera.
- SHT40 y ENS160 permanecen estáticos. El dibujo no simula oscilaciones de temperatura, humedad ni gases.
- `Gemma` e `INTERPRET` comparten el motivo de red para mantener la identidad del modelo. Los demás sensores conservan su símbolo en todas las secciones.
- Un ciclo visual no representa tiempo real, porcentaje completado, sensor válido ni inferencia nueva.
- Activar solo los iconos de tareas o flujos con actividad confirmada. WAIT con Gemma activa puede ocurrir y se presenta por separado.
- DEGRADED conserva el símbolo de aviso y requiere texto de evidencia parcial. No significa sesión finalizada.
- No animar toda la pantalla simultáneamente durante la medición. La galería y el GIF son demostraciones.
- CSS y SVG respetan `prefers-reduced-motion: reduce` y muestran el primer fotograma. Los GIF no pueden responder a esa preferencia por sí solos. Si se usan, la aplicación debe sustituirlos por PNG estáticos.
- Un icono decorativo lleva `aria-hidden="true"`. Un icono que transmite información necesita etiqueta y el estado debe estar también escrito.

## Para Codex u otra IA
Usar los nombres de `manifest.json`. Integrar con el estado real de SENSE y el adaptador existente. Las animaciones son presentación. No modificar reglas A–F, FSM, guiones, cegamiento de Q2 ni observaciones humanas para ajustarse a los recursos.

`lock` acompaña el conteo YOLO oculto mientras la solicitud humana esté pendiente. `power` representa W puntual, nunca Wh. Una misma fuente reutiliza el mismo icono.

Estos recursos se produjeron como SVG y fotogramas deterministas para conservar alineación y transparencia. No requieren una llamada a un modelo para reproducirse.

## Novedades de v2
Se añaden 36 iconos y 6 animaciones. Se conservan los 28 nombres anteriores. Reemplazar juntos la biblioteca web, el atlas y su CSS: el atlas v2 es de 8 × 8 y no se debe mezclar con el CSS de v1. Los SVG individuales conservan sus rutas.

Nuevos iconos: timer, presence, distance, aqi, tvoc, eco2, gemma-text, gemma-image, changes, evidence, context, image, tasks, pending, history, health, diagnostic, telemetry, play, pause, stop, previous, next, refresh, upload, filter, event, observer, quality, stale, unknown, conflict, error, check, theme-light y theme-dark.

Nuevas animaciones: gemma-text, gemma-image, tasks, telemetry, refresh y upload. El importador de ZIP es local: upload no indica que se transmita el archivo a internet.

Corrección de uso: timer para tiempo de ejecución. power exclusivamente para potencia W. Los iconos aqi/tvoc/eco2 representan métricas, mientras ens160 sigue identificando la fuente física.

El archivo UI-MAP.json indica dónde usar cada símbolo y cuándo activar actividad. PROMPT-REDISENO-SENSE.md contiene el encargo de implementación. No hace falta usar los 64 iconos simultáneamente.
