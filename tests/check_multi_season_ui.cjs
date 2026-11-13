const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('static/integration.js', 'utf8');
const code = source.slice(source.indexOf('function seasonChoices('), source.indexOf('async function confirmTmdbTitle(')) + source.slice(source.indexOf('async function trackTmdb('), source.indexOf('\nfunction integrationSettingsSection()', source.indexOf('async function trackTmdb(')));
const calls = [], messages = [], checks = ['1','2','3'].map(value => ({value,checked:true}));
const button = {disabled:false}, picker = {disabled:false}, error = {textContent:''}, modal = {close(){this.closed=true;}};
const form = {seasons:['1','2','3'], querySelectorAll(){return checks;}};
const ctx = vm.createContext({Set, Number, String, console, connection:{selected:{tmdb_id:123,media_type:'tv'},config:{}},
  esc:x=>String(x).replace(/</g,'&lt;'), icon:()=>'',
  FormData:class{constructor(form){this.form=form;}getAll(){return this.form.seasons;}},
  $:(selector)=>selector==='button[type="submit"]'?button:selector==='.season-picker'?picker:selector==='#tmdb-track-error'?error:modal,
  api:async(path,options)=>{const season=options.body.season;calls.push(season);if(season===2) throw Error('网络超时');return {item:{id:season},added_request:season===1,already_exists:season===3};},
  loadItems:async()=>{},renderPage:()=>{},scheduleIntegrationPoll:()=>{},isAdministrator:()=>true,openDetail:id=>messages.push(`detail:${id}`),toast:message=>messages.push(message)});
vm.runInContext(code,ctx);
(async()=>{
  const html=ctx.seasonChoices([{season_number:1},{season_number:2}]);
  assert.equal((html.match(/type="checkbox"/g)||[]).length,2);
  assert.match(html,/可多选/);
  await ctx.trackTmdb({preventDefault(){},target:form});
  assert.deepEqual(calls,[1,2,3]);
  assert.deepEqual(checks.map(c=>c.checked),[false,true,false]);
  assert.match(error.textContent,/已处理 2 季.*第 2 季：网络超时/);
  assert.equal(button.disabled,false); assert.equal(picker.disabled,false); assert(!modal.closed);
  calls.length=0;form.seasons=['2'];ctx.api=async(path,options)=>{calls.push(options.body.season);return {item:{id:2},added_request:true};};
  await ctx.trackTmdb({preventDefault(){},target:form});assert.deepEqual(calls,[2]);assert(messages.includes('detail:2'));
  form.seasons=[];await ctx.trackTmdb({preventDefault(){},target:form});assert.equal(error.textContent,'请至少选择一季。');
  ctx.connection.selected.media_type='movie';form.seasons=[];calls.length=0;await ctx.trackTmdb({preventDefault(){},target:form});assert.deepEqual(calls,[1]);
  console.log('Multiple seasons, partial failure, retry, empty selection and movie verified.');
})().catch(e=>{console.error(e);process.exitCode=1;});
