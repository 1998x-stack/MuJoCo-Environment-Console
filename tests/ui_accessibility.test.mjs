import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source=readFileSync('app/static/app.js','utf8');
const page=readFileSync('app/static/index.html','utf8');
const styles=readFileSync('app/static/app.css','utf8');
function section(start,end){
 const from=source.indexOf(start),to=source.indexOf(end,from);
 assert.ok(from>=0&&to>from,'Missing UI function: '+start);
 return source.slice(from,to);
}
function createHarness(){
 const makeElement=()=>({
  value:'',textContent:'',innerHTML:'',disabled:false,attrs:{},
  setAttribute(k,v){this.attrs[k]=v;},
  classList:{toggle(){},add(){},remove(){}}
 });
 const elements=new Map(),get=key=>{
  if(!elements.has(key))elements.set(key,makeElement());
  return elements.get(key);
 };
 const presetButtons=[10000,50000,200000].map(steps=>({...makeElement(),dataset:{steps:String(steps)}}));
 const state={envs:[],selected:{id:'demo',trainable:true},busy:false,trainingBusy:false,
  runs:[],runsSignature:null,filter:'all'};
 const scope={
  state, $:get, document:{querySelectorAll:selector=>selector==='[data-steps]'?presetButtons:[]},
  esc:v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),
  api:async()=>({runs:[]})
 };
 const js=[
  section('function iconFor(','function renderProblems('),
  section('function updateStepFeedback(){','function updateDetails(){'),
  section('function renderRuns(){','function selectedAlgorithm(){'),
  'globalThis.ui={renderEnvs,updateStepFeedback,updateTelemetry,renderDriverState,renderRuns,refreshRuns};'
 ].join('\n');
 vm.runInNewContext(js,scope,{filename:'ui-harness.js'});
 return {ui:scope.ui,scope,get,state,presetButtons};
}

test('UI exposes keyboard, screen reader and parameter controls',()=>{
 for(const key of ['id="viewerSubscribers"','id="viewerRender"','id="viewerFps"','id="viewerDimensions"',
  'id="stepFeedback"','id="envResultSummary"','aria-pressed="true"','class="skip-link"']){
  assert.ok(page.includes(key),key);
 }
 assert.match(styles, /prefers-reduced-motion/);
 assert.match(styles, /min-height:44px/);
 assert.match(styles, /\.algo-select input:focus-visible\+span/);
 assert.match(styles, /\.telemetry-grid/);
});

test('environment search reports filtered count, selection and safely escapes labels',()=>{
 const {ui,state,get}=createHarness();
 state.envs=[
  {id:'gym:demo',name:'Example <img src=x>',category:'Control',library:'gym',installed:true},
  {id:'custom:other',name:'Pending',category:'Custom',library:'custom',installed:false}
 ];
 state.filter='Control';get('#search').value='example';
 ui.renderEnvs();
 assert.equal(get('#envResultSummary').textContent,'当前显示 1 / 2 个环境');
 const html=get('#envList').innerHTML;
 assert.match(html,/&lt;img src=x&gt;/);
 assert.doesNotMatch(html,/<img src=x>/);
 assert.match(html,/aria-pressed="false"/);
 assert.doesNotMatch(html,/Pending/);
});

test('step presets validate numeric boundaries and disable invalid training',()=>{
 const {ui,get,state,presetButtons}=createHarness();
 get('#timesteps').value='50000';assert.equal(ui.updateStepFeedback(),true);
 assert.equal(get('#startTraining').disabled,false);
 assert.equal(presetButtons[1].attrs['aria-pressed'],'true');
 get('#timesteps').value='0';assert.equal(ui.updateStepFeedback(),false);
 assert.equal(get('#timesteps').attrs['aria-invalid'],'true');
 assert.equal(get('#startTraining').disabled,true);
 get('#timesteps').value='5000001';assert.equal(ui.updateStepFeedback(),false);
 get('#timesteps').value='10000';state.trainingBusy=true;
 assert.equal(ui.updateStepFeedback(),true);
 assert.equal(get('#startTraining').disabled,true);
});

test('telemetry differentiates server-requested rendering from target FPS',()=>{
 const {ui,get}=createHarness();
 ui.updateTelemetry(null);
 assert.equal(get('#viewerRender').textContent,'未启动');
 assert.equal(get('#viewerFps').textContent,'—');
 ui.updateTelemetry({subscribers:0,render_requested:false,fps:12,width:640,height:480});
 assert.equal(get('#viewerSubscribers').textContent,'0');
 assert.equal(get('#viewerRender').textContent,'按需待机');
 assert.match(get('#viewerFps').textContent,/目标/);
 assert.equal(get('#viewerDimensions').textContent,'640 × 480');
 ui.updateTelemetry({subscribers:1,render_requested:true,fps:12,width:640,height:480});
 assert.equal(get('#viewerRender').textContent,'正在请求渲染');
});

test('training runs avoid invented scores and preserve DOM when data unchanged',async()=>{
 const {ui,get,state,scope}=createHarness();
 const run={id:'abcdef000',env_id:'demo',algorithm:'PPO',status:'running',timesteps:10000,
  completed_steps:4000,average_reward:null};
 let runs=[run],writes=0;
 const field=get('#runList');
 Object.defineProperty(field,'innerHTML',{get(){return this._html||'';},set(v){writes++;this._html=v;}});
 scope.api=async()=>({runs});
 await ui.refreshRuns();
 assert.equal(writes,1);
 assert.match(field.innerHTML,/value="40\.0"/);
 assert.doesNotMatch(field.innerHTML,/NaN|平均奖励/);
 await ui.refreshRuns();assert.equal(writes,1,'unchanged polling should not rebuild action buttons');
 runs=[{...run,completed_steps:5500,average_reward:17.5}];
 await ui.refreshRuns();assert.equal(writes,2);
 assert.match(field.innerHTML,/17\.50/);
});
