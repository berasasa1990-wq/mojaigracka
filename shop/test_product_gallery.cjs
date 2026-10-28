const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const source = readFileSync(__dirname + '/static/home.js', 'utf8');
const script = source.slice(source.lastIndexOf('// Product gallery:'));

function button(url) {
  return {dataset: {productImage: url}, attributes: {}, active: false,
    addEventListener(name, callback) {this[name] = callback;},
    setAttribute(name, value) {this.attributes[name] = value;},
    classList: {toggle() {}}};
}

test('thumbnail switches the main picture and zoom, with one selected button', () => {
  const buttons = [button('/media/products/main.avif'), button('/media/products/gallery/extra.avif')];
  const main = {src: buttons[0].dataset.productImage, setAttribute(name, value) {this[name] = value;}, removeAttribute(name) {delete this[name];}};
  const zoom = {src: main.src};
  const document = {
    querySelectorAll() {return buttons;},
    querySelector(selector) {return selector === '[data-product-main-image]' ? main : zoom;},
  };
  vm.runInNewContext(script, {document});
  buttons[1].dataset.productSrcset = '/media/extra-300.webp 300w, /media/extra-800.webp 800w';
  buttons[1].click();
  assert.equal(main.src, buttons[1].dataset.productImage);
  assert.equal(main.srcset, buttons[1].dataset.productSrcset);
  assert.equal(zoom.src, main.src);
  assert.equal(buttons[0].attributes['aria-pressed'], 'false');
  assert.equal(buttons[1].attributes['aria-pressed'], 'true');
  buttons[0].click();
  assert.equal(main.src, '/media/products/main.avif');
  assert.equal(main.srcset, undefined);
  assert.equal(zoom.src, main.src);
  assert.equal(buttons[0].attributes['aria-pressed'], 'true');
});

test('pages without gallery controls remain safe', () => {
  vm.runInNewContext(script, {document: {querySelectorAll() {return [];}}});
});
