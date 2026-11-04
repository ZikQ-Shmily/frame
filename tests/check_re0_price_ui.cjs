const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map(); let click, sent;
function node(selector) { if (!nodes.has(selector)) nodes.set(selector, {innerHTML: '', textContent: ''}); return nodes.get(selector); }
const document = {querySelector: node, addEventListener(name, fn) { if (name === 'click') click = fn; }};
const context = vm.createContext({document, console, setTimeout, clearTimeout, URL,
  $: node, esc: x => String(x ?? ''), icon: () => '', emptyState: () => '', isAdministrator: () => true, openEditor: () => {},
  api: async (url, options) => { sent = {url, body: options.body}; return {item: {}}; },
  refreshIntegrationStatus: async () => {}, loadItems: async () => {}, renderPage: () => {}, openDetail: () => {}, scheduleIntegrationPoll: () => {}, toast: () => {}});
vm.runInContext(fs.readFileSync(__dirname + '/../static/re0.js', 'utf8'), context);
vm.runInContext(`re0Picker.itemId = 'item'; re0Picker.rows = [{slug:'s', uploader:'甲', title:'电影', unlock_points:null, is_unlocked:false, can_unlock:true, can_bind:false}]; renderRe0Results();`, context);
const html = node('#re0-results').innerHTML;
assert(html.includes('默认免费（价格未返回）') && html.includes('解锁并立即入库 · 默认免费'));
assert(!html.includes('null 积分') && !html.includes(' disabled'));
const button = {dataset:{re0:'bind', index:'0'}, disabled:false, isConnected:true};
(async () => { await click({target:{closest:() => button}}); assert.equal(sent.body.allow_unknown_price, true); assert(!('max_points' in sent.body)); console.log('Verified unknown-price label and manual unlock request.'); })().catch(e => {console.error(e); process.exitCode = 1;});
