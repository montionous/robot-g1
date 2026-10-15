'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const emotionNames = {happy:'开心',sad:'悲伤',angry:'生气',calm:'平静',unknown:'无法判断'};
const statusNames = {new:'待接单',acknowledged:'已接单',handling:'处理中',closed:'已完成',false_alarm:'已标记误报',recorded:'已记录'};
const moduleNames = {emotion:'情绪',anomaly:'异常',interaction:'互动'};
const modeNames = {live:'采集记录',replay:'历史 / 回放'};
const needStatuses = {detected:'待处理',in_progress:'处理中',completed:'已完成',cancelled:'已取消',failed:'处理失败'};
const categoryNames = {care:'护理',entertainment:'娱乐',activity:'活动',contact:'联系家人'};
const priorityNames = {urgent:'紧急',high:'高',normal:'普通'};
const transitions = {new:['acknowledged','false_alarm'],acknowledged:['handling','false_alarm'],handling:['closed','false_alarm']};
const pages = {overview:['护理工作台','查看老人摘要，跟进异常与互动待办'],elders:['老人档案','维护老人资料和照护备注'],emotion:['情绪记录','查看识别历史、情绪变化及关联的陪伴会话'],anomaly:['异常记录','查看异常详情、音视频和处置过程'],interaction:['互动记录','查看交流全文、明确需求及办理结果'],maintenance:['系统维护','管理老人身份与模块记录接入'],sources:['数据接入','关联老人身份与服务器上的模块记录']};
const archiveKindNames = {care:'护理咨询',chat:'短聊会话',call:'联系家人',activity:'活动意愿',notification:'工作人员通知',assistance:'护理协助'};
const sessionStatusNames = {active:'未收到结束记录',completed:'已结束',no_event:'未触发会话',failed:'失败',interrupted:'中断',incomplete:'不完整'};
const archiveDetailStatusNames = {initiated:'已发起',requested:'已请求',connected:'记录为已接通',completed:'已结束',interested:'已记录兴趣',pending:'待处理',notified:'已记录通知',consulting:'未结束（咨询）',chatting:'未结束（交流）',ended:'已结束',failed:'失败',cancelled:'已取消',closed:'已关闭'};
const state = {mode:'real',view:'overview',selected:null,overview:null,events:[],alerts:[],history:[],filters:{module:'',elder_id:'',status:''},next:null,total:0,request:0,detailRequest:0,loadingMore:false,archive:{elder_id:null,kind:'',request:0,loaded:false,loading:{sessions:false,business:false,observations:false},sessions:{items:[],total:0,next:null},business:{status:'ready',error:'',items:[],total:0,next:null,availability:{}},observations:{items:[],total:0,next:null},detailRequest:0,detail:null}};
state.needs={items:[],total:0,next:null};state.needFilters={elder_id:'',need_category:'',status:'open'};



async function api(path, body, method) {
  const options = body === undefined ? {} : {method:method || 'POST',headers:{'Content-Type':'application/json','X-Care-Console':'1'},body:JSON.stringify(body)};
  options.signal=AbortSignal.timeout(10000);
  const response = await fetch(path, options);
  if (response.status === 401) {
    location.replace('/login');
    throw new Error('登录已过期，请重新登录。');
  }
  let result;
  try { result = await response.json(); }
  catch (_) { throw new Error(`服务响应异常（HTTP ${response.status}），请稍后重试。`); }
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '填写内容不符合要求，请检查后重试。');
  return result;
}
function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { $('#toast').hidden = true; }, 3500);
}
function dateLabel(value) {
  if (!value) return '未提供墙钟时间';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间不可用' : date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
}
function eventTime(event) {return event.observed_at ? dateLabel(event.observed_at) : event.source_seconds==null?'回放时间轴未提供':`回放 ${Number(event.source_seconds).toFixed(1)} 秒`;}
function pill(value, label) {return `<span class="pill ${escapeHtml(value)}">${escapeHtml(label || statusNames[value] || emotionNames[value] || value)}</span>`;}
function avatar(elder) {return `<span class="avatar">${escapeHtml(elder.name.slice(0,1))}</span>`;}
function elderlyOptions(selected='') {return state.overview.elders.map(p => `<option value="${p.id}" ${String(p.id)===String(selected)?'selected':''}>${escapeHtml(p.name)}${p.room?' · '+escapeHtml(p.room):''}</option>`).join('');}
function profileNote(elder) {
  if (elder.profile_source !== 'interaction') return '';
  return elder.profile_status === 'error'
    ? `<p class="source-error" role="alert">${escapeHtml(elder.profile_error)}</p>`
    : '<p class="source-note">基础资料来自交互档案，刷新时自动更新。</p>';
}
function person(elder) {return `<div class="person-cell">${avatar(elder)}<div><strong>${escapeHtml(elder.name)}</strong><small>${escapeHtml([elder.gender,elder.age==null?'':elder.age+' 岁',elder.room||'未登记房间'].filter(Boolean).join(' · '))}</small></div></div>`;}
function recentEmotion(elder) {return elder.last_emotion && elder.last_emotion.emotion!=='unknown' ? `${elder.last_emotion.inference==='possible'?'可能':''}${emotionNames[elder.last_emotion.emotion]} · ${eventTime(elder.last_emotion)}` : '暂无识别记录';}

function archiveTime(value, basis) {
  if (!value) return '未提供时间';
  if (basis === 'source_timezone_unspecified') return `${escapeHtml(value)}（来源时区未知）`;
  const date=new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : escapeHtml(date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})+'（北京时间）');
}
function archiveItemTime(item, field) {
  return archiveTime(item?.[field], item?.time_basis?.[field]);
}
function archiveStatus(value, names = {}) {
  const raw = value == null || value === '' ? 'unknown' : String(value);
  return pill('unknown', names[raw] || (raw==='unknown'?'未记录状态':raw));
}
function prettyJson(value) {
  try { return JSON.stringify(value, null, 2); } catch (_) { return String(value ?? ''); }
}
function rawDetails(label, value, className = '') {
  if (value === undefined || value === null) return '';
  return `<details class="archive-raw ${className}"><summary>${escapeHtml(label)}</summary><pre>${escapeHtml(prettyJson(value))}</pre></details>`;
}
function archiveRecordLabel(record) {
  const payload = record?.payload || {};
  const stage = typeof payload.stage === 'string' ? payload.stage : '';
  if (record?.kind === 'receipt') return '模块请求 / 播报回执（原始记录）';
  if (payload.input_source === 'derived_interrupt_instruction') return '系统转换的任务指令';
  if (payload.kind === 'companion_interaction_asr' || payload.kind === 'emotion_dialogue_interrupt_command') return '老人语音转写（识别结果）';
  if (payload.kind === 'companion_interaction_speech' || payload.kind === 'emotion_dialogue_stop_confirmation') return '系统播报文本（请求）';
  if (stage.includes('老人说')) return '老人语音转写（原始记录）';
  if (stage.includes('模型输出')) return '模型生成文本（原始记录）';
  if (record?.kind === 'session_end') return '会话结束记录';
  if (record?.kind === 'session_start') return '会话开始记录';
  if (record?.kind === 'recording_gap') return '记录缺口';
  return record?.kind || '会话记录';
}
function archiveRecordText(record) {
  const text = record?.payload?.text;
  return typeof text === 'string' ? text : '';
}
function archiveElderOptions(selected = '') {
  return `<option value="">全部老人</option>${(state.overview?.elders || []).map(elder => `<option value="${escapeHtml(elder.id)}" ${String(elder.id) === String(selected) ? 'selected' : ''}>${escapeHtml(elder.name)}${elder.room ? ` · ${escapeHtml(elder.room)}` : ''}</option>`).join('')}`;
}
function archiveSummary(item) {
  if (!item?.summary) return '<span class="muted">未提供原文摘录</span>';
  const refs = Array.isArray(item.summary_refs) ? item.summary_refs.filter(ref => ref !== null && ref !== undefined).map(String) : [];
  return `<pre class="archive-excerpt">${escapeHtml(item.summary)}</pre>${refs.length ? `<small class="archive-source-ref">原文记录：${refs.map(ref => escapeHtml(ref)).join('、')}</small>` : '<small class="archive-source-ref">原文记录编号未提供</small>'}`;
}
function observationTime(item) {
  if (item?.observed_at) return `观测源时间：${item.observed_at}`;
  if (item?.source_seconds !== null && item?.source_seconds !== undefined) return `视频回放时间轴：${Number(item.source_seconds).toFixed(1)} 秒（未提供墙钟时间）`;
  return '未提供观测时间';
}
function archiveObservationRows(items = state.archive.observations.items || []) {
  if (!items.length) return '<div class="empty">暂无情绪观察历史。无事件不能推断为平静。</div>';
  return `<div class="table-wrap archive-table-wrap"><table class="archive-table"><thead><tr><th>观测时间</th><th>老人</th><th>识别结果</th><th>工作台接收</th><th>原始记录</th></tr></thead><tbody>${items.map(item => `<tr><td>${escapeHtml(observationTime(item))}</td><td>${escapeHtml(item.elder_name || '未提供')}<small class="small-line"><br>记录 #${escapeHtml(item.external_id || item.id)}</small></td><td>${pill(item.emotion,`${emotionNames[item.emotion] || item.emotion || '无法判断'} · ${item.inference === 'possible' ? '可能' : item.inference || '原始值'}`)}</td><td>${archiveTime(item.received_at)}</td><td>${rawDetails('展开原始 JSON',item.raw)}</td></tr>`).join('')}</tbody></table></div>`;
}
function archiveAvailability() {
  const availability = state.archive.business.availability || {};
  const unavailable = Object.entries(availability).filter(([key,value]) => key !== 'tables' && value === 'unavailable').map(([key]) => archiveKindNames[key] || key);
  if (state.archive.business.status!=='ready') return '<span class="muted">尚未确认表可用性</span>';
  if (!unavailable.length) return '<span class="archive-availability-ok">互动业务主表均可读取</span>';
  return `<span class="archive-availability-warn">不可用：${unavailable.map(escapeHtml).join('、')}（不等于无记录）</span>`;
}
function recordToolbar(kindFilter=false) {
  return `<div class="archive-toolbar"><label>老人<select id="archive-elder" aria-label="筛选记录老人">${archiveElderOptions(state.archive.elder_id)}</select></label>${kindFilter?`<label>类别<select id="archive-kind" aria-label="筛选互动类别"><option value="">全部类别</option><option value="companion" ${state.archive.kind==='companion'?'selected':''}>陪伴会话</option>${Object.entries(archiveKindNames).map(([key,name])=>`<option value="${key}" ${state.archive.kind===key?'selected':''}>${name}</option>`).join('')}</select></label>`:''}</div>`;
}
function interactionRows() {
  const business=state.archive.business;
  const items=business.items || [];
  const visible=items.filter(item=>!items.some(parent=>item.parent_key===parent.key && item.source_key===parent.source_key && String(item.elder_id)===String(parent.elder_id)));
  const rows=(state.archive.kind && state.archive.kind!=='companion'?[]:state.archive.sessions.items || []).map(item=>`<tr><td><strong>陪伴会话</strong><small class="small-line">${archiveTime(item.started_at)}</small></td><td>${escapeHtml(item.elder_name)}</td><td>${archiveSummary(item)}</td><td>${archiveStatus(item.status,sessionStatusNames)}</td><td><button class="table-action" data-session="${escapeHtml(item.id)}">查看全文与结果</button></td></tr>`);
  rows.push(...visible.map(item=>`<tr><td><strong>${escapeHtml(archiveKindNames[item.kind]||item.kind)}</strong><small class="small-line">${archiveItemTime(item,'started_at')}</small></td><td>${escapeHtml(item.elder_name)}</td><td>${archiveSummary(item)}${items.some(child=>child.parent_key===item.key && child.source_key===item.source_key && String(child.elder_id)===String(item.elder_id))?'<small class="small-line">含关联办理事项</small>':''}</td><td>${archiveStatus(item.status,archiveDetailStatusNames)}</td><td><button class="table-action" data-business="${escapeHtml(item.key)}">查看全文与结果</button></td></tr>`));
  return `${business.status==='error'?`<p class="source-error" role="alert">${escapeHtml(business.error)}</p>`:''}${rows.length?`<div class="table-wrap"><table><thead><tr><th>类别 / 开始时间</th><th>老人</th><th>内容摘录</th><th>状态</th><th></th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`:'<div class="empty">暂无符合条件的互动记录。</div>'}`;
}
function archiveView() {
  const more=['sessions','business'].filter(type=>state.archive[type].next && (type!=='sessions'||!state.archive.kind||state.archive.kind==='companion')).map(type=>`<button class="button" data-command="archive-more-${type}" ${state.archive.loading[type]?'disabled':''}>${type==='sessions'?'加载更多陪伴会话':'加载更多办理记录'}</button>`).join('');
  return `${recordToolbar(true)}<section class="panel"><div class="panel-heading"><div><h2>交流与办理记录</h2><p>同一来源会话的正文与护理协助、活动通知在详情中关联</p></div></div>${interactionRows()}${more?`<div class="load-more">${more}</div>`:''}<div class="archive-availability">${archiveAvailability()}</div></section><section class="panel"><div class="panel-heading"><h2>互动需求</h2><label>状态<select id="need-status" aria-label="筛选需求状态"><option value="">全部状态</option><option value="open" ${state.needFilters.status==='open'?'selected':''}>待处理与处理中</option>${Object.entries(needStatuses).map(([key,name])=>`<option value="${key}" ${state.needFilters.status===key?'selected':''}>${name}</option>`).join('')}</select></label></div>${state.needs.status==='error'?`<p class="source-error">${escapeHtml(state.needs.error)}</p>`:needTable()}${state.needs.next?'<div class="load-more"><button class="button" data-command="more-needs">加载更多需求</button></div>':''}</section>`;
}
function emotionView() {
  const observations=state.archive.observations;
  const connected=state.overview.sources.some(source=>source.module==='emotion' && source.enabled && (!state.archive.elder_id||String(source.elder_id)===String(state.archive.elder_id)));
  return `${recordToolbar()}<section class="panel"><div class="panel-heading"><h2>识别历史</h2><span class="hint">共 ${observations.total??'—'} 条</span></div>${!observations.items.length&&!connected?'<div class="empty">尚未接入这位老人的情绪识别记录。请在系统维护中检查数据接入。</div>':archiveObservationRows()}${observations.next?'<div class="load-more"><button class="button" data-command="archive-more-observations">加载更多识别记录</button></div>':''}</section><section class="panel"><div class="panel-heading"><div><h2>情绪变化与回应</h2><p>查看触发的回应策略及明确关联的陪伴会话</p></div><span class="hint">共 ${state.total} 条</span></div>${eventTable(state.events)}${state.next?'<div class="load-more"><button class="button" data-command="more">加载更多情绪变化</button></div>':''}</section>`;
}
function renderArchiveContent() {
  if (state.view==='interaction') $('#content').innerHTML=archiveView();
  else if (state.view==='emotion') $('#content').innerHTML=emotionView();
}
async function renderArchive() {
  if (!state.overview) return;
  const request=++state.archive.request, view=state.view, elderId=state.archive.elder_id, kind=state.archive.kind;
  const current=()=>request===state.archive.request && state.view===view && state.archive.elder_id===elderId && state.archive.kind===kind;
  const query=new URLSearchParams({data_mode:state.mode,limit:'30'});
  if (state.archive.elder_id) query.set('elder_id',state.archive.elder_id);
  try {
    if (view==='emotion') {
      const observations=await api(`/api/emotion-observations?${query}`);
      if(!current()) return;
      state.archive.observations=observations;
    } else {
      const businessQuery=new URLSearchParams(query);
      if(state.archive.kind && state.archive.kind!=='companion') businessQuery.set('kind',state.archive.kind);
      const [sessions,business]=await Promise.all([
        !state.archive.kind||state.archive.kind==='companion'?api(`/api/sessions?${query}`):{items:[],total:0,next:null},
        state.archive.kind!=='companion'?api(`/api/business-records?${businessQuery}`):{status:'ready',items:[],total:0,next:null,availability:{}}
      ]);
      if(!current()) return;
      state.archive.sessions=sessions;state.archive.business=business;
    }
    $('#load-error').hidden=true;
    renderArchiveContent();
  } catch(error) {
    if(!current()) return;
    $('#content').innerHTML='<div class="empty">记录读取失败，请重试。</div>';
    $('#load-error').hidden=false;$('#load-error').textContent=error.message;
  }
}
function sessionRecordMarkup(record) {
  const text = archiveRecordText(record);
  return `<article class="archive-record"><div class="archive-record-heading"><strong>${escapeHtml(archiveRecordLabel(record))}</strong><span>序号 ${escapeHtml(record.seq)} · 原文记录 #${escapeHtml(record.id)}</span></div><div class="archive-record-time">记录写入：${archiveTime(record.recorded_at,record.time_basis)}</div>${text ? `<pre class="archive-record-text">${escapeHtml(text)}</pre>` : ''}${rawDetails('展开原始 JSON',record.payload)}</article>`;
}
function renderSessionDetail(detail) {
  const item = detail.item || {};
  const records = detail.records || [];
  $('#event-dialog-title').textContent = '会话完整记录';
  $('#event-detail').innerHTML = `<div class="detail-body archive-detail"><div class="archive-detail-kicker">会话 #${escapeHtml(item.id)} · ${escapeHtml(item.elder_name || '未提供老人')}</div><h3 class="detail-title">陪伴会话</h3><div class="detail-facts"><span>会话状态<strong>${archiveStatus(item.status,sessionStatusNames)} ${pill("unknown",modeNames[item.mode]||item.mode)}</strong></span><span>开始 / 结束<strong>${archiveTime(item.started_at)}<br>结束：${archiveTime(item.ended_at)}</strong></span><span>初始情绪<strong>${escapeHtml(emotionNames[item.initial_emotion] || item.initial_emotion || '无法判断')}</strong></span>${item.end_emotion&&item.end_emotion!=='unknown'?`<span>结束情绪<strong>${escapeHtml(emotionNames[item.end_emotion]||item.end_emotion)}</strong></span>`:''}<span>记录缺口<strong>${escapeHtml(item.gaps ?? 0)}</strong></span><span>结束原因<strong>${escapeHtml(item.end_reason || '未提供')}</strong></span></div>${item.summary ? `<h3 class="subheading">原文摘录</h3>${archiveSummary(item)}` : '<p class="source-note">未提供会话原文摘录。</p>'}${item.last_user_text ? `<h3 class="subheading">最近一次老人语音转写</h3><pre class="context-box">${escapeHtml(item.last_user_text)}</pre>` : ''}${detail.related_event_id?`<p><button class="text-button" data-event="${escapeHtml(detail.related_event_id)}">查看关联情绪变化</button></p>`:''}${rawDetails('展开初始识别原文',item.initial)}<h3 class="subheading">逐条记录</h3><div class="archive-record-list">${records.length ? records.map(sessionRecordMarkup).join('') : '<p class="source-note">暂无逐条记录。</p>'}</div>${detail.next_record !== null && detail.next_record !== undefined ? `<div class="load-more"><button class="button" data-command="archive-more-session-records">加载更多记录</button></div>` : ''}<p class="section-note">语音转写是识别结果，可能与实际话语有差异。文本按记录原样展示。模型生成内容与实际播报回执分别保留，回执不自动等同于老人已听到。</p></div>`;
}
async function openSession(id) {
  state.detailRequest++;
  const token = ++state.archive.detailRequest;
  const mode = state.mode, view = state.view;
  const prefix = '/api';
  const result = await api(`${prefix}/sessions/${encodeURIComponent(String(id))}?limit=100`);
  if (token !== state.archive.detailRequest || mode !== state.mode || state.view !== view || !['interaction','emotion','overview'].includes(view)) return;
  state.archive.detail = {kind:'session',id:String(id),...result,token,prefix};
  renderSessionDetail(state.archive.detail);
  if (!$('#event-dialog').open) $('#event-dialog').showModal();
}
async function loadMoreSessionRecords(element) {
  const detail = state.archive.detail;
  if (!detail || detail.kind !== 'session' || detail.next_record === null || detail.next_record === undefined) return;
  const token = detail.token,mode=state.mode;
  element.disabled = true;
  try {
    const query = new URLSearchParams({after:String(detail.next_record),limit:'100'});
    const result = await api(`${detail.prefix}/sessions/${encodeURIComponent(detail.id)}?${query}`);
    if (token !== state.archive.detailRequest || state.archive.detail !== detail || mode !== state.mode) return;
    detail.records = [...detail.records,...(result.records || [])];
    detail.next_record = result.next_record;
    renderSessionDetail(detail);
  } finally { element.disabled = false; }
}
function businessMessageMarkup(message) {
  return `<article class="archive-record"><div class="archive-record-heading"><strong>${escapeHtml(message.role || '未提供角色')}</strong><span>第 ${escapeHtml(message.round_no)} 轮 · id ${escapeHtml(message.id)}</span></div><div class="archive-record-time">${archiveTime(message.created_at,message.time_basis)}</div><pre class="archive-record-text">${escapeHtml(message.content || '')}</pre>${message.tags !== undefined ? rawDetails('展开标签 JSON',message.tags) : ''}${message.tags_error ? `<p class="source-error">${escapeHtml(message.tags_error)}</p>` : ''}</article>`;
}
function renderBusinessDetail(detail) {
  const item = detail.item || {};
  const messages = detail.messages || [];
  const source = item.source || {};
  $('#event-dialog-title').textContent = '互动记录详情';
  $('#event-detail').innerHTML = `<div class="detail-body archive-detail"><div class="archive-detail-kicker">${escapeHtml(item.key || detail.key || '')} · ${escapeHtml(item.elder_name || '未提供老人')}</div><h3 class="detail-title">${escapeHtml(item.title || archiveKindNames[item.kind] || item.kind || '互动业务')}</h3><div class="detail-facts"><span>类别<strong>${escapeHtml(archiveKindNames[item.kind] || item.kind || '未提供')}</strong></span><span>原始状态<strong>${archiveStatus(item.status,archiveDetailStatusNames)}</strong></span><span>开始 / 结束<strong>${archiveItemTime(item,'started_at')}<br>结束：${archiveItemTime(item,'ended_at')}</strong></span><span>老人<strong>${escapeHtml(item.elder_name || '未提供')} · 交互编号 ${escapeHtml(item.elderly_id || '未提供')}</strong></span></div><h3 class="subheading">原文摘录</h3>${archiveSummary(item)}${item.kind === 'call' ? '<p class="source-note">拨号或请求状态仅保留原始值，不表示实际接通。</p>' : ''}${item.kind === 'activity' ? '<p class="source-note">活动兴趣记录不表示已经出席。</p>' : ''}${item.kind === 'notification' ? '<p class="source-note">通知记录不表示已送达或已被工作人员阅读。</p>' : ''}${item.kind === 'care' || item.kind === 'chat' ? `<h3 class="subheading">逐轮留言</h3>${messages.length ? `<div class="archive-record-list">${messages.map(businessMessageMarkup).join('')}</div>` : source.row?.messages_availability === 'unavailable' || item.facts?.messages_availability === 'unavailable' ? '<p class="source-note">留言表不可用；这不等于没有留言。</p>' : '<p class="source-note">暂无留言记录。</p>'}${detail.next_message ? `<div class="load-more"><button class="button" data-command="archive-more-business-messages">加载更多留言</button></div>` : ''}` : ''}${relatedRecordsMarkup(detail)}${rawDetails('展开事实字段',item.facts)}${rawDetails('展开来源行',source.row)}<p class="section-note">业务状态和时间按来源保留；页面不把会话结束、兴趣登记或通知记录推断为需求完成、出席或通知成功。</p></div>`;
}
function relatedRecordsMarkup(detail) {
  const business=detail.related_business || [], needs=detail.related_needs;
  return `${business.length?`<h3 class="subheading">关联办理结果</h3>${business.map(item=>`<article class="related-record"><strong>${escapeHtml(archiveKindNames[item.kind]||item.kind)}</strong> ${archiveStatus(item.status,archiveDetailStatusNames)}<p>${escapeHtml(item.summary||'未提供说明')}</p><small>${archiveItemTime(item,'started_at')}</small>${rawDetails('展开完整办理内容',item.facts)}${rawDetails('展开办理来源行',item.source?.row)}</article>`).join('')}`:''}${detail.related_business_more?'<p class="source-note">关联结果超过本页上限，请按类别查看后续办理记录。</p>':''}${needs?`<h3 class="subheading">关联需求</h3>${needs.status==='error'?`<p class="source-error" role="alert">${escapeHtml(needs.error)}</p>`:needs.items.length?needs.items.map(need=>`<article class="related-record">${pill(need.status,needStatuses[need.status])} ${pill(need.priority,priorityNames[need.priority])}<p>${escapeHtml(need.summary)}</p><p>${escapeHtml(need.raw_text||'')}</p>${rawDetails('展开需求原始字段',need)}</article>`).join(''):'<p class="source-note">此会话暂无明确关联的需求。</p>'}${needs.next?'<button class="button" data-command="related-more-needs">加载更多关联需求</button>':''}`:''}`;
}
function relatedNeedQuery(item, before) {
  const scene={care:'CARE_CONSULTATION_SUPPORT',chat:'SHORT_COMPANION_CHAT'}[item.kind];
  if(!scene) return null;
  const query=new URLSearchParams({elder_id:String(item.elder_id),source_scene:scene,source_session_id:String(item.key).split(':')[1],limit:'100'});
  if(before) query.set('before',before);
  return query;
}
async function openBusinessRecord(key, expectedElderId=null) {
  const detailToken=++state.detailRequest, token=++state.archive.detailRequest;
  const mode=state.mode, view=state.view;
  let result=await api(`/api/business-records/${encodeURIComponent(String(key))}?limit=100`);
  const current=()=>token===state.archive.detailRequest && detailToken===state.detailRequest && mode===state.mode && view===state.view;
  if(!current()) return;
  if(result.status!=='ready') {toast(result.error||'互动记录不可用');return false;}
  if(expectedElderId!==null && String(result.item.elder_id)!==String(expectedElderId)) return false;
  if(result.item.parent_key) {
    const parent=await api(`/api/business-records/${encodeURIComponent(result.item.parent_key)}?limit=100`);
    if(!current()) return;
    if(parent.status==='ready' && String(parent.item.elder_id)===String(result.item.elder_id) && parent.item.source_key===result.item.source_key) {
      if(!(parent.related_business||[]).some(item=>item.key===result.item.key)) parent.related_business=[result.item,...(parent.related_business||[])];
      result=parent;key=parent.item.key;
    }
  }
  const query=relatedNeedQuery(result.item);
  if(query) {
    try {result.related_needs=await api(`/api/interaction?${query}`);}
    catch(error) {result.related_needs={status:'error',error:error.message,items:[]};}
  }
  if(!current())return;
  state.archive.detail={kind:'business',key:String(key),...result,token};
  renderBusinessDetail(state.archive.detail);
  if(!$('#event-dialog').open)$('#event-dialog').showModal();
  return true;
}
async function loadMoreRelatedNeeds(element) {
  const detail=state.archive.detail;
  if(!detail?.related_needs?.next || element.disabled) return;
  const token=state.archive.detailRequest;
  element.disabled=true;
  try {
    const result=await api(`/api/interaction?${relatedNeedQuery(detail.item,detail.related_needs.next)}`);
    if(token!==state.archive.detailRequest || state.archive.detail!==detail) return;
    if(result.status==='error')throw new Error(result.error);
    detail.related_needs={...result,items:[...detail.related_needs.items,...result.items]};
    renderBusinessDetail(detail);
  } finally {element.disabled=false;}
}
async function loadMoreBusinessMessages(element) {
  const detail = state.archive.detail;
  if (!detail || detail.kind !== 'business' || !detail.next_message) return;
  const token = detail.token;
  element.disabled = true;
  try {
    const query = new URLSearchParams({after:String(detail.next_message),limit:'100'});
    const result = await api(`/api/business-records/${encodeURIComponent(detail.key)}?${query}`);
    if (token !== state.archive.detailRequest || state.archive.detail !== detail) return;
    if (result.status!=='ready') throw new Error(result.error || '留言读取失败');
    detail.messages = [...detail.messages,...(result.messages || [])];
    detail.next_message = result.next_message;
    renderBusinessDetail(detail);
  } finally { element.disabled = false; }
}
async function loadArchiveMore(type, element) {
  if (state.archive.loading[type]) return;
  const resultState = state.archive[type];
  if (!resultState?.next) return;
  const request = state.archive.request;
  state.archive.loading[type] = true;
  element.disabled = true;
  try {
    const query = new URLSearchParams({data_mode:state.mode,before:String(resultState.next),limit:'30'});
    if (state.archive.elder_id) query.set('elder_id',state.archive.elder_id);
    if (type === 'business' && state.archive.kind) query.set('kind',state.archive.kind);
    const endpoint = type === 'sessions' ? '/api/sessions' : type === 'business' ? '/api/business-records' : '/api/emotion-observations';
    const result = await api(`${endpoint}?${query}`);
    if (request !== state.archive.request || !['interaction','emotion'].includes(state.view)) return;
    if (type === 'business' && result.status === 'error') throw new Error(result.error || '互动业务档案读取失败');
    state.archive[type] = {...result,items:[...(resultState.items || []),...(result.items || [])]};
    renderArchiveContent();
  } finally { state.archive.loading[type] = false; element.disabled = false; }
}


async function refresh(manual=false,selectedId=state.selected) {
  const request=++state.request;
  const query=new URLSearchParams({data_mode:'real',limit:'100'});
  if(['emotion','anomaly'].includes(state.view)) Object.entries(state.filters).forEach(([key,value])=>{if(value)query.set(key,value);});
  try {
    const overview=await api('/api/overview');
    if(request!==state.request) return;
    const selected=overview.elders.some(p=>p.id===selectedId)?selectedId:overview.elders[0]?.id||null;
    if(state.archive.elder_id===null) state.archive.elder_id=selected===null?'':String(selected);
    if(state.view==='emotion') {state.filters.elder_id=state.archive.elder_id; if(state.archive.elder_id)query.set('elder_id',state.archive.elder_id);else query.delete('elder_id');}
    const needFilters=state.view==='interaction'?{...state.needFilters,elder_id:state.archive.elder_id}:{elder_id:selected||'',status:'open'};
    const needQuery=new URLSearchParams({data_mode:'real',limit:state.view==='interaction'?'50':'4'});
    Object.entries(needFilters).forEach(([key,value])=>{if(value)needQuery.set(key,value);});
    const [events,alerts,history,needs]=await Promise.all([api(`/api/events?${query}`),api('/api/events?module=anomaly&status=open&limit=4'),selected?api(`/api/events?elder_id=${selected}&module=emotion&limit=5`):{items:[]},api(`/api/interaction?${needQuery}`)]);
    if(request!==state.request) return;
    state.overview=overview;state.events=events.items;state.alerts=alerts.items;state.history=history.items;state.needs=needs;
    state.next=events.next;state.total=events.total;state.selected=selected;
    $('#load-error').hidden=true;$('#nav-count').textContent=overview.stats.open_alerts||'';
    $('#last-updated').textContent='最近更新 '+dateLabel(overview.updated_at);
    if(manual||!document.querySelector('dialog[open]')) render();
    return true;
  } catch(error) {
    if(request!==state.request)return;
    $('#load-error').hidden=false;$('#load-error').textContent='读取失败：'+error.message;
    $('#last-updated').textContent='读取中断；请刷新重试';
    return false;
  }
}
function empty(message, actions=true) {
  return `<div class="empty"><span class="empty-mark">◫</span><h3>${escapeHtml(message)}</h3><p>请从交互模块已有档案建立关联，或登记新老人后接入记录。</p>${actions?'<div class="empty-actions"><button class="button primary" data-command="new-elder">新建老人档案</button></div>':''}</div>`;
}

function metrics() {
  const stats=state.overview.stats;
  return `<div class="metrics"><div class="metric"><div><p>在册老人</p><strong>${state.overview.elders.length}</strong></div><span class="metric-icon">♧</span></div><div class="metric alert"><div><p>待跟进异常</p><strong>${stats.open_alerts}</strong><small>待接单、已接单和处理中</small></div><span class="metric-icon">!</span></div><div class="metric"><div><p>情绪事件</p><strong>${stats.emotions}</strong></div><span class="metric-icon">◡</span></div><div class="metric"><div><p>互动待办</p><strong>${state.overview.interaction.open_needs??'—'}</strong><small>待处理与处理中</small></div><span class="metric-icon">≡</span></div></div>`;
}



function elderTable() {
  if(!state.overview.elders.length) return empty('暂无老人档案');
  return `<div class="table-wrap"><table><thead><tr><th>老人 / 房间</th><th>最近情绪识别</th><th>待跟进异常</th><th></th></tr></thead><tbody>${state.overview.elders.map(elder=>`<tr><td>${person(elder)}</td><td>${escapeHtml(recentEmotion(elder))}</td><td>${elder.open_alerts?pill('new',elder.open_alerts+' 条'):'<span class="muted">0 条</span>'}</td><td><button class="table-action" data-select="${elder.id}" aria-label="查看${escapeHtml(elder.name)}资料">查看</button></td></tr>`).join('')}</tbody></table></div>`;
}

function selectedPanel() {
  const elder=state.overview.elders.find(p=>p.id===state.selected);
  if(!elder) return '<section class="panel"><div class="panel-heading"><h2>老人资料</h2></div><div class="empty">请先登记或关联老人档案。</div></section>';
  const recent=elder.last_emotion&&elder.last_emotion.emotion!=='unknown'?elder.last_emotion:null;
  const history=state.history;
  return `<section class="panel"><div class="panel-heading"><h2>老人资料</h2></div><div class="panel-body"><div class="selected-person">${avatar(elder)}<div><h3>${escapeHtml(elder.name)}</h3><p>${escapeHtml([elder.gender,elder.age==null?'':elder.age+' 岁'].filter(Boolean).join(' · '))}</p><p>房间 / 床位：${escapeHtml(elder.room||'未登记')}</p></div></div>${profileNote(elder)}${recent?`<div class="emotion-now ${recent.emotion}"><div><p>最近情绪识别</p><strong>${recent.inference==='possible'?'可能':''}${emotionNames[recent.emotion]}</strong><p>${eventTime(recent)}${recent.mode==='replay'?' · 历史 / 回放':''}</p></div></div>`:'<p class="small-line">暂无识别记录</p>'}<h3 class="subheading">情绪事件历史</h3>${history.length?`<ol class="history-list">${history.map(event=>`<li><span class="history-time">${eventTime(event)}</span>${pill(event.emotion,event.inference==='possible'?'可能'+emotionNames[event.emotion]:null)}<small>${modeNames[event.mode]||''}</small></li>`).join('')}</ol>`:'<p class="small-line">暂无情绪事件记录</p>'}${elder.notes?`<h3 class="subheading">照护备注</h3><p class="small-line">${escapeHtml(elder.notes)}</p>`:''}</div></section>`;
}
async function openElderProfile(id) {
  state.archive.detailRequest++;
  const token=++state.detailRequest;
  const loaded=await refresh(true,id);
  if(!loaded||token!==state.detailRequest||state.selected!==id) return;
  $('#event-dialog-title').textContent='老人资料与历史';$('#event-detail').innerHTML=`<div class="detail-body">${selectedPanel()}</div>`;
  if(!$('#event-dialog').open) $('#event-dialog').showModal();
}

function alertPanel() {
  const alerts=state.alerts;
  return `<section class="panel"><div class="panel-heading"><div><h2>需要跟进</h2><p>查看异常并记录处置过程</p></div><a href="#anomaly" class="text-button">全部异常</a></div>${alerts.length?`<ul class="alert-list">${alerts.map(event=>`<li><span class="alert-level ${event.level}">${event.level}</span><div class="alert-content"><strong>${escapeHtml(event.title)}</strong><p>${escapeHtml(event.elder_name)} · ${escapeHtml(event.room||'未设床位')} · ${eventTime(event)}</p>${pill(event.status)} <span class="small-line">${modeNames[event.mode]}</span></div><button class="text-button" data-event="${event.id}">处理</button></li>`).join('')}</ul>`:'<div class="empty">暂无待跟进记录。请同时确认数据源是否已接入。</div>'}</section>`;
}
function overview() {
  return `${metrics()}<div class="overview-grid"><section class="panel"><div class="panel-heading"><div><h2>老人摘要</h2><p>最近识别与待跟进情况</p></div><a class="text-button" href="#elders">管理档案</a></div>${elderTable()}<div class="panel-body"><a class="text-button" href="#emotion">查看情绪记录</a> · <a class="text-button" href="#interaction">查看互动记录</a></div></section><div>${alertPanel()}${needPanel()}</div></div>`;
}
function needPanel() {
  const elder=state.overview.elders.find(p=>p.id===state.selected);
  const body=state.mode==='demo'?'<p class="source-note">真实互动需求只在真实记录空间显示。</p>':state.needs.status==='error'?`<p class="source-error" role="alert">${escapeHtml(state.needs.error)}</p>`:!elder?.interaction_elderly_id?'<p class="source-note">请在数据接入页明确关联这位老人的交互身份。</p>':state.needs.items.length?`<ul class="history-list">${state.needs.items.map(need=>`<li>${pill(need.priority,priorityNames[need.priority])} ${escapeHtml(need.summary)}<small>${needStatuses[need.status]} · ${escapeHtml(categoryNames[need.need_category]||need.need_category)}</small><button class="text-button" data-need="${need.id}">查看需求</button></li>`).join('')}</ul>`:'<p class="source-note">这位老人暂无待处理需求；可查看全部需求历史。</p>';
  return `<section class="panel"><div class="panel-heading"><div><h2>待处理互动需求</h2><p>当前选择的老人 · 按紧急程度排序</p></div><a class="text-button" href="#interaction">全部需求</a></div><div class="panel-body">${body}</div></section>`;
}
function needTable() {
  return state.needs.items.length?`<div class="table-wrap"><table><thead><tr><th>提出时间</th><th>老人</th><th>明确需求</th><th>优先级</th><th>需求状态</th><th></th></tr></thead><tbody>${state.needs.items.map(need=>`<tr><td>${dateLabel(need.created_at)}</td><td>${escapeHtml(need.elder_name)}</td><td>${escapeHtml(need.summary)}<small class="small-line"><br>${escapeHtml(categoryNames[need.need_category]||need.need_category)}</small></td><td>${pill(need.priority,priorityNames[need.priority])}</td><td>${pill(need.status,needStatuses[need.status])}</td><td><button class="table-action" data-need="${need.id}">查看</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">暂无符合条件的需求。请确认老人身份已关联；需求由交互场景记录。</div>';
}


function interactionBinding() {
  const connection=state.overview.interaction;
  const bindings=state.overview.elders.filter(elder=>elder.interaction_elderly_id);
  const available=connection.people.filter(person=>person.enabled&&!bindings.some(elder=>elder.interaction_elderly_id===person.id));
  const local=state.overview.elders.filter(elder=>!elder.interaction_elderly_id);
  return `<section class="panel"><div class="panel-heading"><h2>关联交互身份</h2></div><div class="panel-body">${connection.status==='error'?`<p class="source-error" role="alert">${escapeHtml(connection.error)}</p>`:`${bindings.map(elder=>`<p class="source-note">${escapeHtml(elder.name)} → 交互老人 #${elder.interaction_elderly_id}</p>`).join('')}${available.length&&local.length?`<form id="interaction-binding-form" class="source-form"><input type="hidden" name="source_key" value="${escapeHtml(connection.source_key)}"><label>工作台档案<select name="elder_id" required><option value="">请选择</option>${local.map(elder=>`<option value="${elder.id}">${escapeHtml(elder.name)} · ${escapeHtml(elder.room||'未设床位')}</option>`).join('')}</select></label><label>交互模块老人<select name="elderly_id" required><option value="">请选择</option>${available.map(person=>`<option value="${person.id}">#${person.id} ${escapeHtml(person.name)} · ${escapeHtml(person.room||'未设床位')}</option>`).join('')}</select></label><p class="source-note full">核对姓名和床位后关联。两边编号独立；已有绑定保持固定，避免历史需求归属变化。</p><p class="form-error full" role="alert"></p><button class="button primary full" type="submit">保存身份关联</button></form>`:'<p class="source-note">暂无可关联的档案；请先建立工作台档案，或检查交互模块是否有启用的老人。</p>'}`}</div></section>`;
}
function eventTable(events, compact=false) {
  if (!events.length) return `<div class="empty">暂无记录。数据接入后会自动显示；历史回放会单独标记。</div>`;
  return `<div class="table-wrap"><table><thead><tr><th>观察时间</th><th>老人</th><th>事件</th>${compact?'':'<th>等级</th>'}<th>处理状态</th><th></th></tr></thead><tbody>${events.map(event=>`<tr><td>${eventTime(event)}<small class="small-line"><br>${modeNames[event.mode]}</small></td><td>${escapeHtml(event.elder_name)}</td><td>${escapeHtml(event.title)}<small class="small-line"><br>${moduleNames[event.module]}${event.inference==='possible'?' · 可能':''}</small></td>${compact?'':`<td>${event.level?pill(event.level):'<span class="muted">—</span>'}</td>`}<td>${pill(event.status)}</td><td><button class="table-action" data-event="${event.id}">查看</button></td></tr>`).join('')}</tbody></table></div>`;
}
function elders() {
  if(!state.overview.elders.length) return `<section class="panel">${empty('暂无老人档案')}</section>`;
  return `<div class="profile-grid">${state.overview.elders.map(elder=>`<section class="profile-card">${person(elder)}${profileNote(elder)}<p>最近识别：${escapeHtml(recentEmotion(elder))}</p><p>待跟进异常：${elder.open_alerts} 条</p><p>${escapeHtml(elder.notes||'暂无照护备注')}</p><div class="profile-actions"><button class="text-button" data-select="${elder.id}">查看资料与历史</button><button class="text-button" data-edit="${elder.id}">${elder.interaction_elderly_id?'编辑照护备注':'编辑档案'}</button></div></section>`).join('')}</div>`;
}

function eventsView() {
  const connected=state.overview.sources.some(source=>source.module==='anomaly' && source.enabled && (!state.filters.elder_id||String(source.elder_id)===String(state.filters.elder_id)));
  return `<div class="filter-bar"><select id="filter-elder" aria-label="筛选异常记录老人"><option value="">全部老人</option>${elderlyOptions(state.filters.elder_id)}</select><select id="filter-status" aria-label="筛选异常处理状态"><option value="">全部状态</option>${Object.entries(statusNames).filter(([key])=>key!=='recorded').map(([key,name])=>`<option value="${key}" ${state.filters.status===key?'selected':''}>${name}</option>`).join('')}</select></div><section class="panel"><div class="panel-heading"><h2>异常详情与处置</h2><span class="hint">共 ${state.total} 条</span></div>${!state.events.length&&!connected?'<div class="empty">尚未接入异常监测记录。请在系统维护中检查数据接入。</div>':eventTable(state.events)}${state.next?'<div class="load-more"><button class="button" data-command="more">加载更多异常</button></div>':''}</section>`;
}
function maintenanceLinks() {
  return '<div class="maintenance-links"><a href="#maintenance">系统维护</a><a href="#sources">数据接入</a></div>';
}
function maintenanceView() {
  return `${maintenanceLinks()}<section class="panel"><div class="panel-body"><h2>数据接入</h2><p>关联老人身份与服务器上的模块记录，检查读取状态。</p><a class="button" href="#sources">管理数据接入</a></div></section>`;
}
async function renderSources() {
  const viewToken=state.request;
  let candidates=[],candidateError='';
  try {candidates=await api('/api/candidates');}
  catch(error) {candidateError=error.message;}
  if (state.view!=='sources'||viewToken!==state.request) return;
  const sources=state.overview.sources.map(source=>({...source,error:[source.error,source.profile_error].filter(Boolean).join('; ')}));
  $('#content').innerHTML=`${maintenanceLinks()}${candidateError?`<p class="source-error" role="alert">可选文件列表读取失败：${escapeHtml(candidateError)}。仍可填写服务器可读的日志路径。</p>`:''}<section class="panel"><div class="panel-body"><h2>接入配置</h2><p class="source-note">将情绪、异常和互动模块产生的记录关联到老人档案。保存后，后台会持续读取新增记录。请确认老人和该服务器能读取的文件；本机文件不会自动上传到云端。</p></div></section><div class="overview-grid"><div><section class="panel"><div class="panel-heading"><h2>已绑定数据源</h2><button class="text-button" data-command="sync">立即读取</button></div>${sources.length?`<div class="table-wrap"><table><thead><tr><th>模块 / 老人</th><th>读取状态</th><th></th></tr></thead><tbody>${sources.map(source=>`<tr><td><strong>${moduleNames[source.module]} · ${escapeHtml(source.elder_name)}</strong><div class="source-path">${escapeHtml(source.path)}</div><span class="small-line">${modeNames[source.mode]}</span></td><td>${pill(source.error?'new':source.enabled?'closed':'unknown',source.error?'读取异常':source.enabled?'已绑定':'已停用')}<div class="small-line">拒绝记录 ${source.rejected} 条</div>${source.error?`<div class="source-error">${escapeHtml(source.error)}</div>`:''}</td><td>${source.enabled&&state.mode==='real'?`<button class="table-action" data-disable="${source.id}">停用</button>`:''}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">还没有绑定数据源。</div>'}</section><section class="panel"><div class="panel-heading"><h2>三个模块的接入进度</h2></div><div class="panel-body"><p class="source-note">情绪：识别依据、观察历史和交流全文。<br>异常：事件证据、音视频片段和人工处理记录。<br>互动：明确需求、交流全文与六类业务档案。</p><p class="source-note">后台读取各模块的新增记录。这里配置数据关联；日常查看与跟进请使用情绪、异常和互动记录。</p></div></section>${interactionBinding()}</div><section class="panel"><div class="panel-heading"><div><h2>绑定模块记录</h2><p>先明确这段采集对应哪位老人</p></div></div><div class="panel-body">${state.overview.elders.length?`<form id="source-form" class="source-form"><label>老人档案<select name="elder_id" required>${elderlyOptions(state.selected)}</select></label><label>模块<select name="module"><option value="emotion">情绪识别</option><option value="anomaly">异常监测</option><option value="interaction">交流会话日志</option></select></label><label class="full">已发现的记录文件<select id="candidate-file"><option value="">手动填写文件路径</option>${candidates.map((candidate,index)=>`<option value="${index}">${escapeHtml(candidate.label)}</option>`).join('')}</select></label><label class="full">JSONL 文件路径<input name="path" required maxlength="2048" placeholder="模块输出文件的绝对路径"></label><label class="full">采集类型<select name="mode"><option value="replay">历史记录 / 视频回放</option><option value="live">当前实时采集</option></select></label><p class="source-note full">每个数据源固定绑定一位老人。更换老人时请创建新的采集文件并重新绑定，避免历史记录串人。</p><p class="form-error full" role="alert"></p><button class="button primary full" type="submit">绑定并读取记录</button></form>`:'<p class="source-note">请先建立一份老人档案。</p><button class="button primary" data-command="new-elder">新建档案</button>'}</div></section></div>`;
  if ($('#candidate-file')) $('#candidate-file').addEventListener('change',event=>{
    const candidate=candidates[Number(event.target.value)];
    if (event.target.value!==''&&candidate) {
      const form=$('#source-form'); form.elements.path.value=candidate.path;form.elements.module.value=candidate.module;form.elements.mode.value=candidate.mode;
    }
  });
}

function render() {
  $('#new-elder').hidden=['maintenance','sources'].includes(state.view);
  const page=pages[state.view];
  $('#heading').textContent=page[0];$('#page-name').textContent=page[0];$('#eyebrow').textContent=page[1];
  document.querySelectorAll('[data-nav]').forEach(item=>item.classList.toggle('active',item.dataset.nav===(['sources'].includes(state.view)?'maintenance':state.view)));
  if(['sources','interaction','emotion'].includes(state.view)) $('#content').innerHTML='<div class="empty">正在读取记录…</div>';
  if(state.view==='sources') renderSources().catch(error=>{$('#load-error').hidden=false;$('#load-error').textContent=error.message;});
  else if(['interaction','emotion'].includes(state.view)) renderArchive();
  else $('#content').innerHTML=state.view==='overview'?overview():state.view==='elders'?elders():state.view==='maintenance'?maintenanceView():eventsView();
}
function openElder(id) {
  const elder=state.overview?.elders.find(p=>p.id===id); const form=$('#elder-form');
  form.reset();form.elements.elder_id.value=id||'';
  form.dataset.sourceKey=state.overview?.interaction?.source_key||'';
  for (const name of ['name','age','room','notes']) form.elements[name].value=elder?.[name]??'';
  const linked=new Set((state.overview?.elders || []).map(person=>person.interaction_elderly_id));
  const people=(state.overview?.interaction?.people || []).filter(person=>person.enabled&&!linked.has(person.id));
  form.dataset.bound=elder?.interaction_elderly_id?'1':'';
  $('#profile-source-label').hidden=Boolean(elder);
  form.elements.profile_source.innerHTML='<option value="">手动建立本地档案</option>'+people.map(person=>`<option value="${escapeHtml(person.id)}">从交互档案建档：${escapeHtml(person.name)} · ${escapeHtml(person.room||'未设床位')}</option>`).join('');
  updateProfileSource();
  $('.form-error',form).textContent='';$('#elder-dialog-title').textContent=elder?(form.dataset.bound?'编辑照护备注':'编辑老人档案'):'新建老人档案';
  $('#elder-dialog').showModal();
}
function updateProfileSource() {
  const form=$('#elder-form');
  const selected=form.elements.profile_source.value;
  const bound=Boolean(form.dataset.bound);
  const person=(state.overview?.interaction?.people || []).find(person=>person.id===selected);
  for (const field of ['name','age','room']) {
    form.elements[field].readOnly=bound || Boolean(selected);
    if (!bound && !form.elements.elder_id.value) form.elements[field].value=person?.[field]??'';
  }
  $('#profile-source-note').textContent=bound || selected?'基础资料由交互模块维护，这里可编辑照护备注。':'本地档案可先接入记录，核对身份后再关联交互档案。';
}
function safeAttachmentUrl(value) {
  try {
    const url = new URL(String(value || ''), location.origin);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/events/')) return '';
    return `${url.pathname}${url.search}`;
  } catch (_) { return ''; }
}
function eventAttachmentsMarkup(event) {
  const attachments = Array.isArray(event.attachments) ? event.attachments : [];
  if (!attachments.length) return '<p class="source-note">未收到可播放附件。</p>';
  return `<div class="archive-attachments"><h3 class="subheading">附件</h3>${attachments.map(attachment => {
    const url = attachment.available ? safeAttachmentUrl(attachment.url) : '';
    const label = attachment.kind === 'video' ? '视频片段' : '音频片段';
    if (!url) return `<p class="source-note">${escapeHtml(label)}不可用：${escapeHtml(attachment.error || '附件地址不在同源允许范围内')}</p>`;
    const media = attachment.kind === 'video' ? `<video controls preload="metadata" src="${escapeHtml(url)}"></video>` : `<audio controls preload="metadata" src="${escapeHtml(url)}"></audio>`;
    return `<div class="archive-attachment"><strong>${escapeHtml(label)}</strong><small class="small-line">${attachment.bytes == null ? '大小未提供' : `${escapeHtml(attachment.bytes)} 字节`}</small>${media}</div>`;
  }).join('')}</div>`;
}
function eventEvidenceMarkup(event) {
  if (event.module !== 'anomaly') return '';
  const raw = event.raw || {};
  const evidence = raw.evidence && typeof raw.evidence === 'object' ? raw.evidence : {};
  const keys = ['transcript','vlm_desc','feats','cross_check','actions_taken'];
  const labels = {transcript:'语音转写',vlm_desc:'画面描述',feats:'检测特征',cross_check:'交叉核验',actions_taken:'模块策略 / 请求'};
  const fields = keys.map(key => {
    const value = raw[key] !== undefined ? raw[key] : evidence[key];
    if (value === undefined || value === null) return '';
    return `<div class="archive-evidence-field"><strong>${labels[key]}</strong>${typeof value === 'string' ? `<pre class="context-box">${escapeHtml(value)}</pre>` : rawDetails('展开原始值',value)}</div>`;
  }).join('');
  return `${fields ? `<h3 class="subheading">模块原始证据与响应字段</h3><div class="archive-evidence">${fields}</div>` : ''}${rawDetails('展开完整 evidence',raw.evidence)}<p class="source-note">actions_taken 仅表示模块记录的策略或请求；实际处理和通知结果以对应回执或人工记录为准。</p>`;
}
async function openEvent(id) {
  state.archive.detailRequest++;
  state.archive.detail=null;
  const token=++state.detailRequest, mode=state.mode, view=state.view;
  const event=await api(`/api/events/${id}`);
  if (token!==state.detailRequest||mode!==state.mode||view!==state.view||(event.mode==='demo')!==(mode==='demo')) return;
  const next=event.module!=='anomaly'?[]:transitions[event.status]||[];
  $('#event-dialog-title').textContent='事件详情';
  const raw=event.raw || {};
  const strategy=raw.strategy;
  const suggestions=Array.isArray(strategy?.do)?strategy.do.filter(item=>typeof item==='string').slice(0,6):[];
  const strategyPanel=event.module==='emotion'&&strategy?`<div class="context-box"><strong>模块建议回应</strong>${typeof strategy.goal==='string'?`<p>${escapeHtml(strategy.goal)}</p>`:''}${typeof strategy.tone==='string'?`<p>语气：${escapeHtml(strategy.tone)}</p>`:''}${suggestions.length?`<ul>${suggestions.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`:''}<small>策略已记录；互动需求可查看，动作与通知结果以对应模块回执为准。</small></div>`:'';
  const score = typeof event.score === 'number' ? event.score.toFixed(3) : '未提供';
  $('#event-detail').innerHTML=`<div class="detail-body">${pill(event.status)} ${pill('unknown',modeNames[event.mode])}<h3 class="detail-title">${escapeHtml(event.title)}</h3><div class="detail-facts"><span>老人 / 床位<strong>${escapeHtml(event.elder_name)} · ${escapeHtml(event.room||'未设置')}</strong></span><span>观察时间<strong>${eventTime(event)}</strong></span><span>模块 / 等级<strong>${escapeHtml(moduleNames[event.module] || event.module)}${event.level?' / '+escapeHtml(event.level):''}</strong></span><span>识别分数<strong>${score}${event.inference==='possible'?' · 可能情绪':''}</strong></span></div><div class="context-box">${escapeHtml(event.detail||strategy?.goal||'模块未提供额外说明')}</div>${strategyPanel}${event.related_sessions?.length?`<h3 class="subheading">关联陪伴会话</h3>${event.related_sessions.map(session=>`<p><button class="text-button" data-session="${escapeHtml(session.id)}">查看会话全文 · ${escapeHtml(sessionStatusNames[session.status]||session.status)}</button></p>`).join('')}`:''}${event.related_sessions_more?'<p class="source-note">其余会话请在互动记录查看。</p>':''}${event.module==='anomaly'?`<p class="small-line">通知状态：${event.notification==='requested'?'模块请求通知，尚无通道成功回执':'未收到通知通道回执'}。护理处理状态以本页记录为准。</p>${eventEvidenceMarkup(event)}${eventAttachmentsMarkup(event)}`:''}${rawDetails('展开事件原始 JSON',raw)}${event.module==='anomaly'?'<h3 class="subheading">处理记录</h3>':''}${event.module==='anomaly'&&event.actions.length?`<ol class="case-history">${event.actions.map(action=>`<li>${escapeHtml(action.operator)} · ${statusNames[action.status] || escapeHtml(action.status)}<small>${dateLabel(action.created_at)}</small><div>${escapeHtml(action.note)}</div></li>`).join('')}</ol>`:`<p class="small-line">${event.module==='anomaly'?'暂无人工处理记录。':'情绪变化已记录；关联会话保留原始交流内容。'}</p>`}${next.length?`<form id="case-form" class="case-form" data-event-id="${event.id}" data-version="${event.version}"><label>处理操作<select name="status">${next.map(status=>`<option value="${status}">${statusNames[status]}</option>`).join('')}</select></label><label>处理人<input name="operator" required maxlength="80" placeholder="填写实际处理人姓名"></label><label>处理说明<textarea name="note" required minlength="2" maxlength="2000" rows="3" placeholder="记录现场核实情况、采取的措施或误报原因"></textarea></label><p class="form-error" role="alert"></p><button class="button primary" type="submit">保存处理记录</button></form>`:''}<div class="knowledge"><strong>专业知识联动</strong><p>现有护理知识条目待项目审核。第一版不据此自动决策或触发机器人。</p><a href="https://www.cdc.gov/falls/" target="_blank" rel="noopener noreferrer">CDC 老年人跌倒预防</a><a href="https://medlineplus.gov/dizzinessandvertigo.html" target="_blank" rel="noopener noreferrer">MedlinePlus 头晕资料</a></div></div>`;
  if (!$('#event-dialog').open) $('#event-dialog').showModal();
}
async function openNeed(id) {
  state.archive.detailRequest++;
  const token=++state.detailRequest,mode=state.mode,view=state.view;
  const need=await api(`/api/interaction/${id}`);
  if(token!==state.detailRequest||mode!==state.mode||mode!=='real'||view!==state.view) return;
  const kind={CARE_CONSULTATION_SUPPORT:'care',SHORT_COMPANION_CHAT:'chat'}[String(need.source_scene||'').toUpperCase()];
  if(kind && /^[1-9][0-9]*$/.test(String(need.source_session_id||''))) {
    const opened=await openBusinessRecord(`${kind}:${need.source_session_id}`,need.elder_id);
    if(opened!==false)return;
  }
  $('#event-dialog-title').textContent='互动需求详情';
  $('#event-detail').innerHTML=`<div class="detail-body">${pill(need.status,needStatuses[need.status])} ${pill(need.priority,priorityNames[need.priority])}<h3 class="detail-title">${escapeHtml(need.summary)}</h3><div class="detail-facts"><span>老人<strong>${escapeHtml(need.elder_name)} · 交互老人 #${need.elderly_id}</strong></span><span>需求类别<strong>${escapeHtml(categoryNames[need.need_category]||need.need_category)}</strong></span><span>需求登记时间<strong>${dateLabel(need.created_at)}</strong></span><span>最近更新<strong>${dateLabel(need.updated_at)}</strong></span><span>来源场景 / 会话<strong>${escapeHtml(need.source_scene)} / ${escapeHtml(need.source_session_id||'未提供')}</strong></span><span>继续处理方<strong>${escapeHtml(need.handled_by||'未提供')}</strong></span></div><h3 class="subheading">老人原始表达</h3><div class="context-box">${escapeHtml(need.raw_text||'未提供')}</div>${need.details?`<h3 class="subheading">场景扩展信息</h3><pre class="context-box">${escapeHtml(JSON.stringify(need.details,null,2))}</pre>`:''}${need.details_error?`<p class="source-error" role="alert">${escapeHtml(need.details_error)}</p>`:''}${need.completed_at?`<p class="source-note">进入终态：${dateLabel(need.completed_at)}</p>`:''}<p class="source-note">状态由负责处理的交互场景更新。这里查看明确需求及处理状态；对话、通知与动作的实际结果需查看对应模块记录。</p></div>`;
  if(!$('#event-dialog').open) $('#event-dialog').showModal();
}
async function busy(form, operation) {
  const button=$('button[type="submit"]',form), error=$('.form-error',form);
  button.disabled=true;error.textContent='';
  try {await operation();} catch (failure) {error.textContent=failure.message;} finally {button.disabled=false;}
}
document.addEventListener('submit',async event=>{
  const form=event.target;if (!['elder-form','source-form','case-form','interaction-binding-form','password-form'].includes(form.id)) return;event.preventDefault();
  const data=Object.fromEntries(new FormData(form));
  await busy(form,async()=>{
    if (form.id==='password-form') {
      await api('/api/auth/password',data);form.reset();location.replace('/login');return;
    }
    if(['source-form','interaction-binding-form'].includes(form.id)&&state.mode!=='real') throw new Error('请切换到真实记录后操作。');
    if (form.id==='elder-form') {
      const body={name:data.name,age:data.age===''?null:Number(data.age),room:data.room,notes:data.notes};
      let elder;
      if (form.dataset.bound) {
        elder=await api(`/api/elders/${data.elder_id}/notes`,{notes:data.notes},'PUT');
      } else if (!data.elder_id && data.profile_source) {
        elder=await api('/api/elders/from-interaction',{elderly_id:data.profile_source,source_key:form.dataset.sourceKey,notes:data.notes});
      } else {
        elder=await api(data.elder_id?`/api/elders/${data.elder_id}`:'/api/elders',body,data.elder_id?'PUT':'POST');
      }
      $('#elder-dialog').close();state.selected=elder.id;toast('档案已保存');
    } else if (form.id==='source-form') {
      await api('/api/sources',{elder_id:Number(data.elder_id),module:data.module,path:data.path,mode:data.mode});
      await api('/api/sync',{});toast('数据源已绑定，记录开始读取');
    } else if (form.id==='interaction-binding-form') {
      await api(`/api/elders/${Number(data.elder_id)}/interaction-binding`,{elderly_id:data.elderly_id,source_key:data.source_key});
      toast('交互身份已关联');
    } else {
      const token=state.detailRequest, mode=state.mode;
      await api(`/api/events/${form.dataset.eventId}/actions`,{...data,version:Number(form.dataset.version)});
      toast('处理记录已保存');
      if (token===state.detailRequest&&mode===state.mode) await openEvent(Number(form.dataset.eventId));
    }
    await refresh(true);
  });
});
document.addEventListener('click',async event=>{
  const element=event.target.closest('button,[data-select]');if (!element) return;
  try {
    if (element.id==='change-password') {$('#password-form').reset();$('.form-error',$('#password-form')).textContent='';$('#password-dialog').showModal();}
    else if (element.id==='logout') {await api('/api/auth/logout',{});location.replace('/login');}
    else if (element.dataset.close) {if(element.dataset.close==='event-dialog') {state.detailRequest++;state.archive.detailRequest++;}$('#'+element.dataset.close).close();}
    else if (element.dataset.edit) openElder(Number(element.dataset.edit));
    else if (element.dataset.event) await openEvent(Number(element.dataset.event));
    else if (element.dataset.need) await openNeed(element.dataset.need);
    else if (element.dataset.session) await openSession(element.dataset.session);
    else if (element.dataset.business) await openBusinessRecord(element.dataset.business);
    else if (element.dataset.command==='related-more-needs') await loadMoreRelatedNeeds(element);
    else if (element.dataset.command==='archive-more-session-records') await loadMoreSessionRecords(element);
    else if (element.dataset.command==='archive-more-business-messages') await loadMoreBusinessMessages(element);
    else if (element.dataset.command?.startsWith('archive-more-')) await loadArchiveMore(element.dataset.command.slice('archive-more-'.length),element);
    else if (element.dataset.select) await openElderProfile(Number(element.dataset.select));
    else if (element.dataset.disable) {await api(`/api/sources/${element.dataset.disable}`,{},'DELETE');toast('已停用，已入库历史继续保留');await refresh(true);}
    else if (element.dataset.command==='new-elder'||element.id==='new-elder') openElder();
    else if (element.dataset.command==='sync'||element.id==='refresh') {await api('/api/sync',{});await refresh(true);}
    else if (element.dataset.command==='more-needs') {
      if(state.loadingMore||!state.needs.next) return;
      const token=state.request;state.loadingMore=true;element.disabled=true;
      const query=new URLSearchParams({data_mode:state.mode,before:state.needs.next,limit:'50',...Object.fromEntries(Object.entries({...state.needFilters,elder_id:state.archive.elder_id}).filter(([,value])=>value))});
      try {
        const result=await api(`/api/interaction?${query}`);
        if(token===state.request) {
          if(result.status==='error') throw new Error(result.error);
          state.needs={...result,items:[...state.needs.items,...result.items]};renderArchiveContent();
        }
      } finally {state.loadingMore=false;element.disabled=false;}
    }
    else if (element.dataset.command==='more') {
      if (state.loadingMore||!state.next) return;
      const token=state.request;state.loadingMore=true;element.disabled=true;
      const query=new URLSearchParams({data_mode:state.mode,before:state.next,limit:100,...Object.fromEntries(Object.entries(state.filters).filter(([,v])=>v))});
      try {
        const result=await api(`/api/events?${query}`);
        if (token===state.request) {state.events=[...state.events,...result.items];state.next=result.next;if(state.view==='emotion')renderArchiveContent();else render();}
      } finally {state.loadingMore=false;element.disabled=false;}
    }
  } catch (error) {toast(error.message);}
});
document.addEventListener('change',event=>{
  if (event.target.id==='elder-profile-source') updateProfileSource();
  if (['archive-elder','archive-kind'].includes(event.target.id)) {
    state.archive.request++;
    $('#content').innerHTML='<div class="empty">正在读取记录…</div>';
    state.archive[event.target.id==='archive-elder'?'elder_id':'kind']=event.target.value;
    if(event.target.id==='archive-elder') {state.filters.elder_id=event.target.value;refresh(true);}
    else renderArchive();
  }
  const mappings={'filter-elder':'elder_id','filter-status':'status'};
  if (mappings[event.target.id]) {state.filters={...state.filters,[mappings[event.target.id]]:event.target.value};refresh(true);}
  const needs={'need-elder':'elder_id','need-category':'need_category','need-status':'status'};
  if(needs[event.target.id]) {state.needFilters={...state.needFilters,[needs[event.target.id]]:event.target.value};refresh(true);}
});
$('#event-dialog').addEventListener('cancel',()=>{state.detailRequest++;state.archive.detailRequest++;});
function applyRoute() {
  const requested=location.hash.slice(1);
  state.view=({events:'anomaly',archive:'interaction',replays:'maintenance'})[requested] || (pages[requested]?requested:'overview');
  state.filters={module:['emotion','anomaly'].includes(state.view)?state.view:'',elder_id:state.view==='emotion'?state.archive.elder_id||'':'',status:''};
}
window.addEventListener('hashchange',()=>{
  state.archive.request++;state.detailRequest++;state.archive.detailRequest++;
  if($('#event-dialog').open)$('#event-dialog').close();
  applyRoute();$('#content').innerHTML='<div class="empty">正在读取记录…</div>';refresh(true);
});
applyRoute();
function updateClock() {$('#clock').textContent=new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'});}
updateClock();refresh(true);
api('/api/auth/session').then(session=>{
  if (session.enabled && session.authenticated) {
    $('#operator-name').textContent=session.username;
    $('#logout').hidden=false;
    $('#change-password').hidden=false;
    $('#connection-label').textContent='护理工作台';
  }
}).catch(error=>toast(error.message));
$('#password-dialog').addEventListener('close',()=>$('#password-form').reset());
setInterval(()=>{if (!document.querySelector('dialog[open]')&&!$('#content').contains(document.activeElement)&&!['maintenance','sources','anomaly','emotion','interaction'].includes(state.view)) refresh();},5000);
