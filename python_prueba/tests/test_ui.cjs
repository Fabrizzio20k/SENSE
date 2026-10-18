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
