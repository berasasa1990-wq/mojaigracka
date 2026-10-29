const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/static/meta-pixel.js', 'utf8');
function page(events, storage = new Map(), consent = true) {
  const handlers = {}, scripts = [];
  const window = {metaMarketingConsent: consent, addEventListener(name, fn) { handlers[name] = fn; }};
  const context = {window, document: {getElementById() { return {textContent: JSON.stringify({pixel_id:'1761995418366231', events})}; }, createElement() { return {}; }, head:{append(script) { scripts.push(script); }}}, localStorage:{getItem:key=>storage.get(key), setItem:(key,value)=>storage.set(key,value)}};
  vm.runInNewContext(source, context);
  return {window, handlers, scripts, context, tracks:()=>window.fbq?.queue.filter(args=>args[0]==='trackSingle') || []};
}
const event = {name:'Purchase',event_id:'unique-order-id',data:{value:42,currency:'BAM'}};
test('bootstrap once, actual data, deduplication ID and local refresh guard', () => {
  const storage = new Map();
  const first = page([event], storage);
  vm.runInNewContext(source, first.context);
  assert.equal(first.scripts.length, 1);
  assert.equal(first.tracks().length, 1);
  assert.equal(first.tracks()[0][4].eventID, event.event_id);
  assert.equal(first.tracks()[0][3].value, 42);
  assert.equal(page([event], storage).tracks().length, 0);
});
test('no tracking or script before consent; grant then revoke', () => {
  const instance = page([{...event,name:'PageView'}], new Map(), false);
  assert.equal(instance.scripts.length, 0);
  instance.handlers['meta:consent-change']({detail:{marketing:true}});
  assert.equal(instance.scripts.length, 1);
  assert.equal(instance.tracks().length, 1);
  instance.handlers['meta:consent-change']({detail:{marketing:false}});
  instance.handlers['meta:commerce']({detail:{...event,event_id:'new-add',name:'AddToCart'}});
  assert.equal(instance.tracks().length, 1);
});
test('AJAX success event sent only once', () => {
  const instance=page([]);
  const add={...event,name:'AddToCart'};
  instance.handlers['meta:commerce']({detail:add});
  instance.handlers['meta:commerce']({detail:add});
  assert.equal(instance.tracks().length,1);
});
