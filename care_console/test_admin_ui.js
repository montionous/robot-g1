'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, 'static/app.js'), 'utf8');
const startup = source.indexOf("document.addEventListener('submit'");
assert(startup > 0, 'Browser startup boundary must exist');

function createUI() {
  const nodes = new Map();
  const document = {querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      hidden: false, textContent: '', innerHTML: '', open: false,
      addEventListener() {},
      showModal() { this.open = true; }, close() { this.open = false; },
    });
    return nodes.get(selector);
  }};
  const elders = [1, 2].map(id => ({
    id, name: `测试老人${id === 1 ? 'A' : 'B'}`, gender: '男', age: 76, room: `${id}01`,
    notes: '', open_alerts: 0, last_emotion: null,
  }));
  let failedElder = null;
  const requests = [];
  const responses = new Map();
  let delayedPath = null, delayedRequest = null;
  const sandbox = {
    document, URLSearchParams, AbortSignal,
    async fetch(request) {
      requests.push(request);
      const url = new URL(request, 'https://console.example.invalid');
      if (url.pathname === delayedPath || request === delayedPath) await delayedRequest;
      if (responses.has(url.pathname)) return responses.get(url.pathname);
      let result;
      if (url.pathname === '/api/overview') {
        result = {elders, stats: {events: 0, emotions: 0, open_alerts: 0}, sources: [],
          interaction: {status: 'ready', people: [], bound_elders: 0, open_needs: 0},
          updated_at: '2026-10-14T00:00:00Z'};
      } else if (url.pathname === '/api/events') {
        const id = Number(url.searchParams.get('elder_id'));
        if (id && id === failedElder) throw new Error('simulated profile history failure');
        result = {items: id ? [{emotion: id === 1 ? 'happy' : 'sad', mode: 'replay',
          source_seconds: id * 111}] : [], total: id ? 1 : 0, next: null};
      } else if (url.pathname === '/api/interaction') {
        result = {status: 'ready', items: [], total: 0, next: null};
      } else if (url.pathname === '/api/events/1') {
        result = {id:1,module:'anomaly',mode:'live',title:'疑似跌倒',status:'new',
          elder_name:'视频回放',source_seconds:11.5,level:'L3',raw:{},actions:[],attachments:[]};
      } else if (url.pathname === '/api/sessions/1') {
        result = {item:{id:'1',elder_name:'文本回放',mode:'replay',status:'completed',
          summary:'回放原文',last_seq:1,gaps:0},records:[],next_record:null};
      } else {
        throw new Error(`Unexpected mocked request: ${request}`);
      }
      return {ok: true, status: 200, json: async () => result};
    },
  };
  vm.createContext(sandbox);
  // Load the actual UI functions without browser startup; every request uses the mock above.
  vm.runInContext(source.slice(0, startup), sandbox);
  vm.runInContext('render = () => {}', sandbox);
  let clickHandler;
  document.addEventListener=(kind,handler)=>{if(kind==='click') clickHandler=handler;};
  const clickStart=source.indexOf("document.addEventListener('click'");
  const clickEnd=source.indexOf("document.addEventListener('change'",clickStart);
  vm.runInContext(source.slice(clickStart,clickEnd),sandbox);
  return {
    node: selector => document.querySelector(selector),
    select: id => vm.runInContext(`openElderProfile(${id})`, sandbox),
    failHistory: id => { failedElder = id; },
    formalEvent: () => vm.runInContext("state.view='interaction'; openEvent(1)", sandbox),
    formalSession: () => vm.runInContext("state.view='interaction'; openSession('1')", sandbox),
    requests,
    evaluate: code => vm.runInContext(code, sandbox),
    respond: (path, response) => responses.set(path, response),
    defer(path) {
      delayedPath=path;
      let release;
      delayedRequest=new Promise(resolve=>{release=resolve;});
      return release;
    },
    clickCommand(command) {
      const button={dataset:{command},disabled:false};
      return clickHandler({target:{closest:()=>button}});
    },
  };
}

test('Failed B history request cannot open B with the previous A history', async () => {
  const ui = createUI();
  await ui.select(1);
  assert.equal(ui.node('#event-dialog').open, true);
  const previous = ui.node('#event-detail').innerHTML;
  assert.match(previous, /测试老人A/);
  assert.match(previous, /回放 111\.0 秒/);
  ui.node('#event-dialog').close();
  ui.failHistory(2);

  await ui.select(2);
  assert.equal(ui.node('#event-dialog').open, false);
  assert.equal(ui.node('#event-detail').innerHTML, previous);
  assert.match(ui.node('#load-error').textContent, /simulated profile history failure/);
});

test('Interaction records show existing consultation text without a separate empty session section', () => {
  const ui=createUI();
  ui.evaluate(`state.overview={elders:[],sources:[]}; state.archive.business={status:'ready',total:1,items:[{key:'care:3',kind:'care',elder_id:'1',elderly_id:'7',source_key:'owner-db',summary:'已有咨询全文',status:'ended'}]}`);
  const markup=ui.evaluate('archiveView()');
  assert.match(markup,/已有咨询全文/);
  assert.doesNotMatch(markup,/暂无会话记录|情绪观察历史/);
});

test('Only an explicit same-source parent removes a child from the primary list', () => {
  const ui=createUI();
  ui.evaluate(`state.archive.sessions.items=[]; state.archive.business.items=[
    {key:'care:3',kind:'care',elder_id:'1',source_key:'owner-db',summary:'same'},
    {key:'assistance:10',parent_key:'care:3',kind:'assistance',elder_id:'1',source_key:'owner-db',summary:'same'},
    {key:'assistance:11',parent_key:'care:3',kind:'assistance',elder_id:'2',source_key:'owner-db',summary:'same'},
    {key:'assistance:12',parent_key:'care:3',kind:'assistance',elder_id:'1',source_key:'another-db',summary:'same'}];`);
  const markup=ui.evaluate('interactionRows()');
  assert.doesNotMatch(markup,/data-business="assistance:10"/);
  assert.match(markup,/data-business="assistance:11"/);
  assert.match(markup,/data-business="assistance:12"/);
});

test('A non-JSON server failure produces a useful HTTP error and leaves source configuration usable', async () => {
  const ui=createUI();
  ui.respond('/api/candidates',{ok:false,status:500,json:async()=>{throw new SyntaxError('Internal Server Error');}});
  ui.evaluate("state.view='sources'; state.overview={elders:[],sources:[],interaction:{status:'ready',people:[]}};");
  await ui.evaluate('renderSources()');
  assert.match(ui.node('#content').innerHTML,/HTTP 500/);
  assert.match(ui.node('#content').innerHTML,/接入配置/);
  assert.doesNotMatch(ui.node('#content').innerHTML,/Unexpected token/);
});

test('The first emotion query follows the default elder shown by the filter', async () => {
  const ui=createUI();
  ui.evaluate("state.view='emotion';state.filters.module='emotion';");
  await ui.evaluate('refresh(true)');
  const query=ui.requests.find(path=>path.startsWith('/api/events?data_mode='));
  assert.equal(new URL(query,'https://test.invalid').searchParams.get('elder_id'),'1');
});

test('Loading emotion changes does not reset already paged observations', async () => {
  const ui=createUI();
  ui.evaluate("state.view='emotion';state.overview={elders:[],sources:[]};state.next=5;state.archive.observations={items:[{id:1},{id:2}],total:2};");
  await ui.clickCommand('more');
  assert.equal(ui.evaluate('state.archive.observations.items.length'),2);
  assert.ok(!ui.requests.some(path=>path.startsWith('/api/emotion-observations')));
});

test('An old elder response cannot render under the newly selected elder', async () => {
  const ui=createUI();
  ui.evaluate("state.view='interaction';state.overview={elders:[],sources:[]};state.archive.elder_id='1';");
  ui.respond('/api/sessions',{ok:true,status:200,json:async()=>({items:[],total:0,next:null})});
  ui.respond('/api/business-records',{ok:true,status:200,json:async()=>({status:'ready',items:[{key:'care:1',summary:'A-private-text'}],total:1,next:null})});
  const release=ui.defer('/api/business-records');
  const loading=ui.evaluate('renderArchive()');
  ui.evaluate("state.archive.elder_id='2';");
  release();
  await loading;
  assert.doesNotMatch(ui.node('#content').innerHTML,/A-private-text/);
});

test('A child beyond the parent result limit retains all original fields in the canonical detail', async () => {
  const ui=createUI();
  ui.evaluate("state.view='interaction';");
  const response=data=>({ok:true,status:200,json:async()=>data});
  ui.respond('/api/business-records/assistance%3A201',response({status:'ready',item:{key:'assistance:201',parent_key:'care:3',kind:'assistance',elder_id:'1',source_key:'db-a',facts:{user_description:'完整原话-201'}},messages:[]}));
  ui.respond('/api/business-records/care%3A3',response({status:'ready',item:{key:'care:3',kind:'care',elder_id:'1',source_key:'db-a'},related_business:[],messages:[]}));
  await ui.evaluate("openBusinessRecord('assistance:201')");
  assert.match(ui.node('#event-detail').innerHTML,/完整原话-201/);
  assert.equal(ui.evaluate('state.archive.detail.item.key'),'care:3');
});

test('Successful B selection opens B with only B history', async () => {
  const ui = createUI();
  await ui.select(1);
  ui.node('#event-dialog').close();

  await ui.select(2);
  const detail = ui.node('#event-detail').innerHTML;
  assert.equal(ui.node('#event-dialog').open, true);
  assert.match(detail, /测试老人B/);
  assert.match(detail, /回放 222\.0 秒/);
  assert.doesNotMatch(detail, /测试老人A|回放 111\.0 秒/);
});

test('Anomaly detail uses the formal endpoint and retains the care workflow', async () => {
  const ui = createUI();
  await ui.formalEvent();
  assert.deepEqual(ui.requests, ['/api/events/1']);
  assert.match(ui.node('#event-detail').innerHTML, /疑似跌倒|视频回放/);
  assert.match(ui.node('#event-detail').innerHTML, /id="case-form"|保存处理记录/);
});

test('Session detail uses the formal endpoint', async () => {
  const ui = createUI();
  await ui.formalSession();
  assert.deepEqual(ui.requests, ['/api/sessions/1?limit=100']);
  assert.match(ui.node('#event-detail').innerHTML, /文本回放/);
});

test('A slow event cannot overwrite the subsequently opened session', async () => {
  const ui = createUI();
  const release = ui.defer('/api/events/1');
  const eventRequest = ui.formalEvent();
  await ui.formalSession();
  release();
  await eventRequest;
  assert.match(ui.node('#event-detail').innerHTML, /文本回放/);
  assert.doesNotMatch(ui.node('#event-detail').innerHTML, /疑似跌倒/);
});

test('A slow session cannot overwrite the subsequently opened event', async () => {
  const ui = createUI();
  const release = ui.defer('/api/sessions/1');
  const sessionRequest = ui.formalSession();
  await ui.formalEvent();
  release();
  await sessionRequest;
  assert.match(ui.node('#event-detail').innerHTML, /疑似跌倒/);
  assert.doesNotMatch(ui.node('#event-detail').innerHTML, /文本回放/);
});

test('System maintenance retains data access and has no test-record entry', () => {
  const ui=createUI();
  const markup=ui.evaluate('maintenanceView()');
  assert.match(markup,/href="#sources"/);
  assert.doesNotMatch(markup,/测试记录|#replays/);
  assert.doesNotMatch(source,/api\/replays|function replayView|function renderReplays/);
});
