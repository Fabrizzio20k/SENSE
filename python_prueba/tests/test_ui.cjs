// Preparado para node --test tests/test_ui.cjs; no inicia la app ni requiere navegador.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomFillSync} = require('node:crypto');

const page = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const source = page.slice(page.indexOf('function requestKey()'), page.indexOf('function tell('));
function generator(crypto) {
  return vm.runInNewContext(source + '\nrequestKey;', {
    globalThis: {crypto}, Uint8Array, keySequence: 0,
    Date: {now: () => 1}, Math: {random: () => 0.5}
  });
}

test('usa randomUUID cuando existe', () => {
  assert.equal(generator({randomUUID: () => 'native-key'})(), 'native-key');
});
test('HTTP sin randomUUID usa bytes aleatorios sin lanzar TypeError', () => {
  const key = generator({getRandomValues: randomFillSync});
  const values = Array.from({length: 100}, () => key());
  assert.equal(new Set(values).size, 100);
  assert.ok(values.every(value => /^[0-9a-f]{32}$/.test(value)));
});
test('sin crypto mantiene claves distintas incluso en el mismo milisegundo', () => {
  const key = generator(undefined);
  const values = Array.from({length: 100}, () => key());
  assert.equal(new Set(values).size, 100);
  assert.ok(values.every(value => value.length > 0 && value.length <= 128));
});

// DOM mínimo para las guardas y la vista previa; no sustituye revisión en navegador.
function panel(search = '', protocol = 'http:') {
  function element(id = '') {
    const classes = new Set();
    return {id, value: '', textContent: '', disabled: false, hidden: false, checked: false,
      dataset: {}, children: [], attributes: {},
      classList: {remove: value => classes.delete(value), toggle(value, enabled) {
        if (enabled) classes.add(value); else classes.delete(value);
      }},
      append(...items) {this.children.push(...items)},
      prepend(item) {this.children.unshift(item)},
      replaceChildren(...items) {this.children = items},
      setAttribute(name, value) {this.attributes[name] = value},
      removeAttribute(name) {delete this.attributes[name]},
      addEventListener() {}, focus() {this.focused = true}
    };
  }
  const ids = Array.from(page.matchAll(/\bid="([^"]+)"/g), match => match[1]);
  assert.equal(new Set(ids).size, ids.length, 'IDs únicos para controles y navegación');
  const elements = Object.fromEntries(ids.map(id => [id, element(id)]));
  const fields = ['variant', 'duration', 'scenario', 'block', 'space', 'phase'].map(id => elements[id]);
  Object.assign(elements.variant, {value: 'rules-v1', options: ['rules-v1', 'A', 'B', 'C', 'D', 'E_visual'].map(value => ({value}))});
  elements.duration.value = '600'; elements.scenario.value = 'exploration';
  elements.block.value = elements.space.value = 'unassigned'; elements.phase.value = 'development';
  const views = ['prepare', 'configure', 'monitor', 'records'];
  const nav = views.map(view => Object.assign(element(), {dataset: {view}}));
  const questions = ['presence', 'environment', 'environment_trend', 'count_people', 'interpret_context', 'describe_image']
    .map(question => Object.assign(element(), {dataset: {question}}));
  const controls = [elements.finish, elements.cancel, elements['power-submit'], ...questions];
  const selectors = {'.workspace': views.map(view => elements['view-' + view]), '.nav button': nav,
    '[data-view]': nav, '.session-field': fields, '.active-control': controls, '.record-control': [], '.question': questions, '#states span': []};
  const canvas = {clearRect() {}, fillText() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}};
  elements.chart.getContext = () => canvas;
  const calls = {fetch: 0, stream: 0, timer: 0};
  const context = vm.createContext({
    document: {getElementById(id) {assert.ok(elements[id], 'ID existente: ' + id); return elements[id]},
      querySelectorAll(selector) {assert.ok(selectors[selector], 'Selector previsto: ' + selector); return selectors[selector]},
      createElement: () => element()},
    location: {search, protocol}, URLSearchParams,
    fetch: async () => {calls.fetch++; throw Error('Sin red en estas pruebas')},
    EventSource: function() {calls.stream++; throw Error('Sin stream en estas pruebas')},
    setInterval() {calls.timer++}
  });
  const script = page.slice(page.indexOf('<script>') + 8, page.indexOf('</script>'));
  // El arranque se invoca explícitamente en las pruebas que lo necesitan.
  vm.runInContext(script.slice(0, script.lastIndexOf('connect();')), context);
  return {context, elements, questions, nav, calls, run: code => vm.runInContext(code, context)};
}

test('vista previa por URL o archivo: navega sin red, temporizador, sesiones ni modelos', async () => {
  for (const [search, protocol] of [['?preview=1', 'http:'], ['', 'file:']]) {
    const ui = panel(search, protocol);
    await ui.run('connect()');
    assert.deepEqual(ui.calls, {fetch: 0, stream: 0, timer: 0});
    assert.equal(ui.elements['preview-banner'].hidden, false);
    assert.equal(ui.elements.checks.children.length, 6);
    assert.equal(ui.elements.start.disabled, true);
    assert.equal(ui.elements.prepare.disabled, true);
    await ui.run("api('/v1/runtime/prepare', {})").then(() => assert.fail('Debe bloquear la API'), error => assert.match(error.message, /vista previa/));
    await ui.run("action(() => api('/v1/runs', {}))");
    ui.run("showView('monitor')");
    assert.equal(ui.elements['view-monitor'].hidden, false);
    assert.equal(ui.elements['view-prepare'].hidden, true);
    assert.equal(ui.elements['monitor-heading'].focused, true);
    assert.equal(ui.nav[2].attributes['aria-current'], 'step');
    assert.deepEqual(ui.calls, {fetch: 0, stream: 0, timer: 0});
  }
});

test('admisión y acciones permanecen bloqueadas sin diagnóstico o durante cierre', () => {
  const ui = panel();
  ui.run('enable()');
  assert.equal(ui.elements.start.disabled, true);
  ui.run('health={can_start_session:false}; enable()');
  assert.equal(ui.elements.start.disabled, true);
  ui.run('health.can_start_session=true; enable()');
  assert.equal(ui.elements.start.disabled, false);
  ui.run("active=true; runVariant='D'; closing=true; enable()");
  assert.equal(ui.elements.start.disabled, true);
  assert.ok(ui.questions.every(button => button.disabled));
  ui.run('closing=false; health=null; enable()');
  assert.ok(ui.questions.every(button => button.disabled));
  assert.equal(ui.elements.finish.disabled, true);
});

test('las consultas respetan variantes y replay rechaza W físicos', () => {
  const ui = panel();
  ui.run("active=true; health={can_start_session:false}; runVariant='C'; enable()");
  const disabled = name => ui.questions.find(button => button.dataset.question === name).disabled;
  assert.equal(disabled('count_people'), false);
  assert.equal(disabled('interpret_context'), true);
  assert.equal(disabled('describe_image'), true);
  ui.run("runVariant='D'; enable()");
  assert.equal(disabled('interpret_context'), false);
  ui.run("runVariant='E_visual'; enable()");
  assert.equal(disabled('count_people'), true);
  assert.equal(disabled('describe_image'), false);
  ui.run("mode='replay'; runVariant='rules-v1'; enable()");
  assert.equal(ui.elements['power-submit'].disabled, true);
});

test('una lectura ausente se muestra desconocida y un conteo cero se conserva', () => {
  const ui = panel();
  ui.run("readings({temperature_c:0}, {tvoc_ppb:0}); renderAnswer({status:'historical', content_json:{visible_person_count:0}})");
  assert.equal(ui.elements.temperature.textContent, 0);
  assert.equal(ui.elements.humidity.textContent, '—');
  assert.equal(ui.elements.tvoc.textContent, 0);
  assert.equal(ui.elements.eco2.textContent, '—');
  assert.equal(ui.elements['answer-content'].children[0].textContent, '0 personas detectadas en la imagen.');
  assert.equal(ui.elements['answer-status'].textContent, 'Histórico');
  assert.equal(ui.elements['visible-count'].textContent, '—');
  ui.run('readings({}, {}, {usable_for_reported_values:true, latest:{values:{visible_person_count:0}}, receipt_age_s:2})');
  assert.equal(ui.elements['visible-count'].textContent, 0);
  ui.run('readings({}, {}, {usable_for_reported_values:false, latest:{values:{visible_person_count:3}}, receipt_age_s:40})');
  assert.equal(ui.elements['visible-count'].textContent, '—');
});

test('texto del modelo se representa como texto con inferencias y desconocidos separados', () => {
  const ui = panel();
  ui.run(`renderAnswer({question:'interpret_context', content_json:{validated:{
    answer:'<img src=x onerror=alert(1)>',
    inferred:[{claim:'Hipótesis pendiente', evidence_ids:['obs-1']}], unknown:['Causa física']
  }}})`);
  const children = ui.elements['answer-content'].children;
  assert.equal(children[0].textContent, '<img src=x onerror=alert(1)>');
  assert.ok(children.some(child => child.textContent === 'Inferencias del modelo'));
  assert.ok(children.some(child => child.textContent === 'Desconocidos'));
});

test('al detener se pueden resolver W, pero no cerrar ni iniciar otra medición con pendientes', () => {
  const ui = panel();
  ui.elements['power-task-select'].value = 'power-30';
  ui.run(`runId='test'; active=false; health={can_start_session:true};
    runRecord={manifest:{power_protocol:{id:'manual-power-v1'}}, measurement:{status:'pending_review', can_close:false}}; enable()`);
  assert.equal(ui.elements['power-submit'].disabled, false);
  assert.equal(ui.elements.start.disabled, true);
  assert.equal(ui.elements['close-measurement'].disabled, true);
  ui.run('runRecord.measurement.can_close=true; enable()');
  assert.equal(ui.elements['close-measurement'].disabled, false);
  ui.run("runRecord.measurement.status='closed_with_omissions'; runRecord.measurement.can_close=false; enable()");
  assert.equal(ui.elements['power-submit'].disabled, true);
  assert.equal(ui.elements.start.disabled, false);
});

test('una lectura atrasada exige su tiempo real y no rellena automáticamente el instante previsto', () => {
  const ui = panel();
  ui.elements['power-task-select'].value = 'power-0';
  ui.run(`active=true; runRecord={measurement:{elapsed_s:65, interval_s:30,
    tasks:[{task_id:'power-0', due_elapsed_s:0}]}}; powerTaskHelp()`);
  assert.equal(ui.elements['power-time'].required, true);
  assert.equal(ui.elements['power-time'].value, '');
  assert.match(ui.elements['power-task-help'].textContent, /tiempo real/);
});
