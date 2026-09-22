'use strict';
const $ = id => document.getElementById(id);
const state = {token: '', project: null, view: 'studio', section: null, zoom: 24, selection: [0, 8], busy: false};
const arrows = ['↑', '↓', '←', '→', '↖', '↗', '↙', '↘', '●'];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = seconds => `${Math.floor(Math.max(0,seconds)/60)}:${String(Math.floor(Math.max(0,seconds)%60)).padStart(2,'0')}`;
function toast(message, error = false) { $('toast').textContent = message; $('toast').className = error ? 'error' : ''; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, error ? 10000 : 5000); }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-SaberMapper-Token':state.token},body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}
async function run(label, callback) {
  if (state.busy) { toast('Please wait for the current operation to finish.'); return; }
  state.busy = true; $('busy-text').textContent = label; $('busy').hidden = false;
  try { return await callback(); } catch (error) { toast(error.message, true); } finally { state.busy = false; $('busy').hidden = true; }
}
function download(name, data, type='application/json') {
  const url = URL.createObjectURL(new Blob([typeof data === 'string' ? data : JSON.stringify(data,null,2)],{type}));
  const link = document.createElement('a'); link.href=url; link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function fileBase64(file) { return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Could not read the selected file'));reader.readAsDataURL(file);}); }
function currentId() { if (!state.project) throw new Error('Open a project first'); return state.project.project.id; }
function totalBeats() { if (!state.project) return 64; return Math.max(8,...state.project.arrangement.sections.map(s=>beatNumber(s.start_beat)+beatNumber(s.length_beats))); }
function beatNumber(value) { if (typeof value === 'string' && value.includes('/')) { const [a,b]=value.split('/').map(Number);return a/b; } return Number(value); }
function beatSeconds(beat) {
  const arrangement=state.project.arrangement, bpm=arrangement.song.bpm;
  let current=0, seconds=arrangement.song.audio_offset_seconds, tempo=bpm;
  for (const e of (arrangement.tempo_events || []).slice().sort((a,b)=>beatNumber(a.beat)-beatNumber(b.beat))) {
    const at=beatNumber(e.beat); if(at>beat) break; seconds+=(at-current)*60/tempo;current=at;tempo=e.bpm;
  }
  return seconds+(beat-current)*60/tempo;
}
function secondsBeat(seconds) { let lo=0,hi=Math.max(totalBeats()+8, seconds*20); for(let i=0;i<35;i++){const m=(lo+hi)/2;if(beatSeconds(m)>seconds)hi=m;else lo=m;}return (lo+hi)/2; }
async function refreshProjects() {
  const projects=await api('/api/projects');
  $('project-list').innerHTML=projects.length?projects.map(p=>`<button class="project-link ${state.project?.project.id===p.id?'active':''}" data-project="${esc(p.id)}" title="${esc(p.title)}">${esc(p.title)}</button>`).join(''):'<p class="hint">Your tracks will appear here.</p>';
  $('project-list').querySelectorAll('[data-project]').forEach(b=>b.onclick=()=>run('Opening project…',()=>loadProject(b.dataset.project)));
  return projects;
}
async function loadProject(id) { $('arcviewer-handoff').hidden=true; state.project=await api(`/api/projects/${id}`); state.selection=[0,Math.min(8,totalBeats())]; showView('studio'); renderProject(true);await refreshProjects(); }
function showView(view) { state.view=view;document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==`view-${view}`);document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));$('view-label').textContent=' / '+({studio:'Studio',corpus:'Pattern library',research:'Research & evaluation'}[view]);if(view==='corpus')run('Reading the corpus…',renderCorpus);if(view==='research')run('Opening research…',renderResearch);if(view==='studio' && state.project)requestAnimationFrame(drawWaveform); }
function renderProject(audioChanged=false) {
  const d=state.project,a=d.arrangement;
  $('welcome').hidden=true;$('project-view').hidden=false;
  $('project-title').textContent=a.song.title;$('project-subtitle').textContent=`${a.song.artist} · ${a.difficulty.name} · Standard · ${d.project.composition_origin}`;
  $('project-origin').textContent=d.project.origin==='original-demo'?'ORIGINAL DEMO / EDITABLE ARRANGEMENT':'LOCAL TRACK / EDITABLE ARRANGEMENT';
  $('stat-bpm').textContent=Number(a.song.bpm.toFixed(2));$('stat-duration').textContent=time(d.project.duration_seconds);$('stat-notes').textContent=d.notes.length;
  $('stat-density').textContent=`${(d.notes.length/d.project.duration_seconds).toFixed(2)} notes/sec`;
  const errors=d.diagnostics.filter(x=>x.severity==='error'), warnings=d.diagnostics.filter(x=>x.severity==='warning');
  $('stat-checks').textContent=errors.length?`${errors.length} errors`:warnings.length?`${warnings.length} flags`:'Clear';$('stat-check-detail').textContent='structural checks';
  $('bpm').value=a.song.bpm;$('offset').value=a.song.audio_offset_seconds;$('timing-badge').textContent=d.project.timing_reviewed?'Reviewed':'Needs review';$('timing-badge').className='badge '+(d.project.timing_reviewed?'good':'warn');$('confirm-timing').textContent=d.project.timing_reviewed?'Clear review':'Mark reviewed \u2713';
  const timing=d.analysis.timing||{};$('timing-confidence').textContent=`${timing.source || 'Local tempo estimate'}. Check the beat grid at the start, middle and end. ${timing.confidence !== undefined ? `Relative grid score: ${typeof timing.confidence==='number' ? timing.confidence.toFixed(2) : timing.confidence}.` : ''}`;
  $('sections').innerHTML=a.sections.map(s=>`<button class="section-card" data-section="${esc(s.id)}"><div class="name"><span>${esc(s.id)}</span><span>${s.locked?'▣':s.resolved?'↗':'?'}</span></div><div class="intent">${esc(s.intent)}</div><div class="meta">BEATS ${esc(s.start_beat)} — ${beatNumber(s.start_beat)+beatNumber(s.length_beats)} · ${s.notes.length} literal notes ${s.patterns.length?'· '+s.patterns.length+' motifs':''}</div></button>`).join('');
  $('sections').querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>openSection(b.dataset.section));
  $('section-strip').innerHTML=a.sections.map(s=>`<button data-seek="${beatNumber(s.start_beat)}" title="${esc(s.intent)}">${esc(s.id)}</button>`).join('');
  $('section-strip').querySelectorAll('[data-seek]').forEach(b=>b.onclick=()=>{$('audio').currentTime=beatSeconds(Number(b.dataset.seek));state.selection=[Number(b.dataset.seek),Number(b.dataset.seek)+8];drawTimeline();});
  $('diagnostic-count').textContent=d.diagnostics.length;
  $('diagnostics').innerHTML=d.diagnostics.length?d.diagnostics.map(x=>`<div class="diagnostic ${esc(x.severity)}"><strong>${esc(x.code.replaceAll('_',' '))}</strong><br>${esc(x.message)}${x.section_id?`<br><small>${esc(x.section_id)}</small>`:''}</div>`).join(''):'<div class="diagnostic good">✓ No hard structural faults detected.<br><span class="muted">Timing and playability still need review.</span></div>';
  const metrics=Object.entries(d.movement.metrics||{}).filter(([,v])=>typeof v==='number').slice(0,7);
  $('movement').innerHTML=metrics.length?metrics.map(([k,v])=>`<div><span>${esc(k.replaceAll('_',' '))}</span><strong>${Number(v.toFixed(2))}</strong></div>`).join(''):'<div>Movement estimates appear for authored notes.</div>';
  $('feedback-list').innerHTML=d.feedback.map(f=>`<div class="feedback-item"><small>BEATS ${esc(f.start_beat)}–${esc(f.end_beat)} · ${f.object_ids.length} notes · ${esc(f.revision.slice(0,8))} <a href="/api/projects/${currentId()}/files/feedback/${f.id}.json" download>JSON ↓</a></small><p>${esc(f.text)}</p></div>`).join('');
  $('history').innerHTML=d.history.map(h=>`<option value="${h}" ${h===d.revision?'selected':''}>${h.slice(0,12)} ${h===d.revision?'· current':''}</option>`).join('');
  $('review-count').textContent=`${(d.reviews||[]).filter(r=>r.playtested).length} entries`;
  $('arrangement-editor').value=JSON.stringify(a,null,2);$('editor-state').textContent=`Saved ${d.revision.slice(0,10)}`;
  if(audioChanged){$('audio').src=`/api/projects/${d.project.id}/files/song.ogg`;$('play').textContent='▶';$('play').setAttribute('aria-label','Play audio');}
  drawTimeline();requestAnimationFrame(drawWaveform);renderStage();
}
function drawTimeline() {
  if(!state.project)return;
  const notes=state.project.notes,z=Number($('zoom').value),maxBeat=totalBeats(),width=Math.max(600,Math.ceil(maxBeat*z+75)),h=318,left=48;
  const svg=$('timeline');svg.setAttribute('width',width);svg.setAttribute('viewBox',`0 0 ${width} ${h}`);
  const [start,end]=state.selection;let parts=[`<rect width="${width}" height="${h}" fill="#111720"/>`];
  for(let lane=0;lane<4;lane++){const y=42+lane*62;parts.push(`<rect x="${left}" y="${y}" width="${width-left}" height="62" fill="${lane%2?'#141d28':'#111923'}"/><text x="12" y="${y+34}" fill="#687c95" font-size="9" font-family="sans-serif">L${lane+1}</text>`);}
  for(let b=0;b<=maxBeat;b++){const x=left+b*z;parts.push(`<line x1="${x}" y1="28" x2="${x}" y2="290" stroke="${b%4===0?'#344255':'#202c3a'}" stroke-width="${b%4===0?1:0.5}"/>`);if(b%4===0)parts.push(`<text x="${x+3}" y="18" fill="#8193aa" font-size="9" font-family="sans-serif">${b}</text>`);}
  parts.push(`<rect x="${left+start*z}" y="28" width="${Math.max(0,(end-start)*z)}" height="262" fill="#b9f18d" opacity="0.055" stroke="#b9f18d" stroke-opacity="0.5"/>`);
  const beatmap=state.project.beatmap||{};
  for(const wall of beatmap.obstacles||[]){parts.push(`<rect x="${left+wall.b*z}" y="${42+wall.x*62}" width="${Math.max(2,wall.d*z)}" height="${Math.min(wall.w,4-wall.x)*62}" fill="#8093aa" fill-opacity="0.13" stroke="#6c7d93" stroke-dasharray="4 3"><title>Obstacle at beat ${wall.b}, duration ${wall.d}</title></rect>`);}
  for(const bomb of beatmap.bombNotes||[]){const x=left+bomb.b*z,y=42+bomb.x*62+(2-bomb.y)*18+12;parts.push(`<circle cx="${x}" cy="${y}" r="6" fill="#b3bfd0"/><text x="${x}" y="${y+3}" text-anchor="middle" fill="#152032" font-size="10">×</text>`);}
  for(const obj of [...(beatmap.sliders||[]),...(beatmap.burstSliders||[])]){const x=left+obj.b*z,tx=left+obj.tb*z,y=42+obj.x*62+(2-obj.y)*18+12,ty=42+obj.tx*62+(2-obj.ty)*18+12;parts.push(`<path d="M${x},${y} C${(x+tx)/2},${y} ${(x+tx)/2},${ty} ${tx},${ty}" fill="none" stroke="${obj.c===0?'#f77a92':'#62c8ed'}" stroke-opacity="0.5" stroke-width="2"/>`);}
  const flagged=new Set(state.project.diagnostics.flatMap(d=>d.object_ids||[]));
  for(const n of notes){const x=left+n.beat*z,y=42+n.x*62+(2-n.y)*18+12,color=n.color===0?'#f77a92':'#62c8ed',selected=n.beat>=start&&n.beat<end;parts.push(`<g data-note="${esc(n.id)}"><rect x="${x-7}" y="${y-7}" width="14" height="14" rx="3" fill="${color}" fill-opacity="${selected?1:0.65}" stroke="${flagged.has(n.id)?'#f4c776':'none'}" stroke-width="2"/><text x="${x}" y="${y+4}" text-anchor="middle" fill="#101827" font-size="11" font-family="sans-serif" font-weight="bold" pointer-events="none">${arrows[n.direction]}</text><title>${esc(n.id)} · beat ${n.beat} · row ${n.y} · ${n.color===0?'left':'right'} hand</title></g>`);}
  parts.push(`<line id="playhead" x1="${left}" y1="26" x2="${left}" y2="291" stroke="#b9f18d" stroke-width="1.5"/><text x="${left}" y="309" fill="#526b85" font-size="8" font-family="sans-serif">TIME →   /   NOTE POSITION WITHIN EACH LANE: TOP · MIDDLE · BOTTOM</text>`);
  svg.innerHTML=parts.join('');$('range-start').value=start;$('range-end').value=end;$('selected-count').textContent=`${notes.filter(n=>n.beat>=start&&n.beat<end).length} notes`;updatePlayhead();
}
function drawWaveform() {
  if(!state.project)return;
  const canvas=$('waveform'),rect=canvas.getBoundingClientRect();if(!rect.width)return;
  canvas.width=Math.ceil(rect.width*devicePixelRatio);canvas.height=70*devicePixelRatio;const ctx=canvas.getContext('2d');ctx.scale(devicePixelRatio,devicePixelRatio);
  const bins=state.project.analysis.waveform?.bins||[],w=rect.width;ctx.clearRect(0,0,w,70);ctx.fillStyle='#688981';
  const scale=Math.max(0.1,...bins.map(v=>Math.max(Math.abs(v.min),Math.abs(v.max))));
  bins.forEach((b,i)=>{const x=i*w/bins.length;ctx.fillRect(x,35-b.max*28/scale,Math.max(1,w/bins.length-1),Math.max(1,(b.max-b.min)*28/scale));});
  const duration=state.project.project.duration_seconds;ctx.fillStyle='#b9f18d';ctx.fillRect($('audio').currentTime/duration*w,0,1,70);
}
function updatePlayhead(){if(!state.project)return;const beat=secondsBeat($('audio').currentTime),x=48+beat*Number($('zoom').value),head=$('playhead');if(head){head.setAttribute('x1',x);head.setAttribute('x2',x);}$('play-time').textContent=`${time($('audio').currentTime)} / ${time(state.project.project.duration_seconds)}`;renderStage();}
function renderStage(){if(!state.project)return;const current=$('audio').currentTime;const active=state.project.notes.filter(n=>Math.abs(beatSeconds(n.beat)-current)<0.16);$('stage').innerHTML=Array.from({length:12},(_,i)=>{const x=i%4,y=2-Math.floor(i/4),n=active.find(v=>v.x===x&&v.y===y);return `<div ${n?`class="${n.color===0?'red-note':'blue-note'}"`:''}>${n?arrows[n.direction]:''}</div>`;}).join('');}
function openSection(id){state.section=id;const section=state.project.arrangement.sections.find(s=>s.id===id);$('section-title').textContent=id;$('section-editor').value=JSON.stringify(section,null,2);$('section-editor').readOnly=section.locked;$('save-section').disabled=section.locked;$('toggle-lock').textContent=section.locked?'Unlock section':'Lock section';$('section-dialog').showModal();}
async function saveArrangement(arrangement){state.project=await api(`/api/projects/${currentId()}/save`,{arrangement,revision:state.project.revision});renderProject();await refreshProjects();toast('Arrangement saved. Unrelated sections and revision history are preserved.');}
async function renderCorpus(){const data=await api('/api/corpus');$('corpus-summary').innerHTML=`<div><span>SOURCE MAPS</span><strong>${data.rows.length}</strong></div><div><span>PHRASES</span><strong>${data.pattern_count}</strong></div><div><span>MOTIF FAMILIES</span><strong>${data.group_count ?? data.groups.length}</strong></div><div><span>ARCHIVE STORAGE</span><strong>${((data.report.archive_bytes||0)/1048576).toFixed(1)}</strong><small>MB</small></div>`;$('corpus-rows').innerHTML=data.rows.length?`<table><thead><tr><th>Exact version</th><th>Status</th><th>Archive</th><th>Retention</th></tr></thead><tbody>${data.rows.map(r=>`<tr><td title="${esc(r.version_hash)}">${esc(r.version_hash.slice(0,16))}…</td><td>${esc(r.status)}${r.error?`<br><small>${esc(r.error)}</small>`:''}</td><td>${((r.archive_bytes||0)/1048576).toFixed(1)} MB</td><td>${r.retain_audio?'Retain exact audio':'Derived features'}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">Import a local map ZIP or fetch an exact BeatSaver version to begin.</div>';renderPatterns(data.patterns.slice(0,12).map(pattern=>({pattern,reason:'Source phrase · review before reuse'})));}
function renderPatterns(items){$('pattern-results').innerHTML=items.length?items.map((item,i)=>{const p=item.pattern;return `<article class="pattern-card"><h3>${esc(p.difficulty)} · ${p.length_beats} beats</h3><div>${p.note_count} notes · ${p.nps} NPS · ${p.bpm} BPM</div><small>${esc(item.reason)}</small><small>SOURCE ${esc(p.version_hash.slice(0,12))} · BEAT ${p.start_beat}</small><button class="text-button" data-pattern="${i}">Download phrase ↓</button></article>`;}).join(''):'<div class="empty">No compatible phrases remain. Add other source tracks or adjust the query; the active song is excluded.</div>';$('pattern-results').querySelectorAll('[data-pattern]').forEach(b=>b.onclick=()=>run('Preparing the source phrase\u2026',async()=>{const p=items[Number(b.dataset.pattern)].pattern;download(`phrase-${b.dataset.pattern}.json`,p.notes?p:await api('/api/corpus/pattern',{id:p.id}));}));}
async function renderResearch(){const data=await api('/api/research'),profile=data.profile,knowledge=data.knowledge,tickets=data['ticket-status'];const notes=knowledge.notes||[];const rows=tickets.tickets||[];$('research-content').innerHTML=`<div class="research-grid"><div class="panel"><div class="panel-head"><h2>Player calibration</h2><span class="badge">HISTORICAL EVIDENCE</span></div><div class="knowledge-note"><p>${esc(profile.summary||'Historical ScoreSaber and BeatLeader evidence is available through the profile CLI. New playtests should establish current preferences.')}</p><pre class="profile-data">${esc(JSON.stringify(profile.statistics||profile,null,2))}</pre><p>Scores measure performance, not taste. Record named liked and disliked sections before adapting the profile.</p></div></div><div class="panel"><div class="panel-head"><h2>Evaluation protocol</h2><span class="badge">SINGLE-RATER STUDY</span></div><div class="knowledge-note"><p>${esc(data.protocol.summary||'Keep song families together. Compare with a rules baseline; record timing, enjoyment, fatigue and revision effort separately.')}</p><p>Use the independently operated assistant to author and revise. Feedback never triggers a model call.</p><p>Preview → instruction → revision → export → in-game playtest. Record a go / revise / stop decision.</p></div></div></div><div class="panel research-notes"><div class="panel-head"><h2>Mapping knowledge</h2></div>${notes.length?notes.map(n=>`<article class="knowledge-note"><h3>${esc(n.title)}</h3><p>${esc(n.summary)}</p><a href="${esc(n.source)}" target="_blank" rel="noreferrer">Primary source ↗</a></article>`).join(''):'<p class="empty">See docs/mapping-knowledge.md for sourced guidance and the technical review rubric.</p>'}</div><div class="panel"><div class="panel-head"><h2>Ticket coverage</h2><span class="muted">Implementation evidence and human validation are separate</span></div><table><thead><tr><th>Ticket</th><th>Capability</th><th>Evidence</th></tr></thead><tbody>${rows.map(t=>`<tr><td>${esc(t.id)}</td><td>${esc(t.title)}</td><td>${esc(t.status)}</td></tr>`).join('')}</tbody></table></div>`;}

document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));
$('new-project').onclick=$('welcome-import').onclick=()=>$('import-dialog').showModal();$('close-import').onclick=()=>$('import-dialog').close();$('close-section').onclick=()=>$('section-dialog').close();
$('create-demo').onclick=()=>run('Creating original audio and analysing the demo…',async()=>{state.project=await api('/api/demo',{});renderProject(true);await refreshProjects();toast('Demo ready. Play the audio and explore the arrangement.');});
$('audio-file').onchange=()=>{if(!$('import-title').value)$('import-title').value=$('audio-file').files[0]?.name.replace(/\.[^.]+$/,'')||'';};
$('import-form').onsubmit=e=>{e.preventDefault();run('Importing audio and estimating timing…',async()=>{const file=$('audio-file').files[0];if(!file)throw new Error('Choose an audio file');if(file.size>64*1048576)throw new Error('Choose a file smaller than 64 MB');const data={filename:file.name,audio:await fileBase64(file),title:$('import-title').value,artist:$('import-artist').value,bpm:$('import-bpm').value||null};state.project=await api('/api/projects/import',data);$('import-dialog').close();showView('studio');renderProject(true);await refreshProjects();toast('Track imported. Review the grid before composing.');});};
$('play').onclick=async()=>{const audio=$('audio');try{if(audio.paused)await audio.play();else audio.pause();}catch(e){toast(`Audio playback failed: ${e.message}`,true);}};
$('audio').onplay=()=>{$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','Pause audio');};$('audio').onpause=()=>{$('play').textContent='▶';$('play').setAttribute('aria-label','Play audio');};$('audio').ontimeupdate=()=>{updatePlayhead();drawWaveform();};$('audio').onloadedmetadata=updatePlayhead;$('speed').onchange=()=>$('audio').playbackRate=Number($('speed').value);$('zoom').oninput=drawTimeline;
$('waveform').onclick=e=>{if(!state.project)return;const r=e.currentTarget.getBoundingClientRect();$('audio').currentTime=(e.clientX-r.left)/r.width*state.project.project.duration_seconds;};
let dragStart=null;$('timeline').onpointerdown=e=>{if(!state.project)return;const r=e.currentTarget.getBoundingClientRect();dragStart=Math.max(0,Math.round((e.clientX-r.left-48)/Number($('zoom').value)*4)/4);e.currentTarget.setPointerCapture(e.pointerId);};$('timeline').onpointerup=e=>{if(dragStart===null)return;const r=e.currentTarget.getBoundingClientRect(),end=Math.max(0,Math.round((e.clientX-r.left-48)/Number($('zoom').value)*4)/4);state.selection=[Math.min(dragStart,end),Math.max(dragStart,end)+0.25];dragStart=null;drawTimeline();};
for(const id of ['range-start','range-end'])$(id).onchange=()=>{const a=Number($('range-start').value),b=Number($('range-end').value);if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b<=a){toast('Choose an increasing, nonnegative beat range.',true);return;}state.selection=[a,b];drawTimeline();};
$('snapshot').onclick=()=>download('sabermapper-timeline.svg',new XMLSerializer().serializeToString($('timeline')),'image/svg+xml');
$('download-arrangement').onclick=()=>download('arrangement.json',state.project.arrangement);
$('save-feedback').onclick=()=>run('Saving feedback…',async()=>{await api(`/api/projects/${currentId()}/feedback`,{revision:state.project.revision,start_beat:state.selection[0],end_beat:state.selection[1],text:$('feedback-text').value});$('feedback-text').value='';state.project=await api(`/api/projects/${currentId()}`);renderProject();toast('Feedback saved. Ask your assistant to read the project feedback files.');});
$('save-arrangement').onclick=()=>run('Validating the arrangement…',()=>saveArrangement(JSON.parse($('arrangement-editor').value)));
$('arrangement-editor').oninput=()=>$('editor-state').textContent='Unsaved edits';$('reset-editor').onclick=()=>{$('arrangement-editor').value=JSON.stringify(state.project.arrangement,null,2);$('editor-state').textContent='Unsaved edits discarded';};
$('save-section').onclick=()=>run('Saving the section…',async()=>{const updated=JSON.parse($('section-editor').value);if(updated.id!==state.section)throw new Error('Preserve the section ID');const arrangement=structuredClone(state.project.arrangement);arrangement.sections[arrangement.sections.findIndex(s=>s.id===state.section)]=updated;await saveArrangement(arrangement);$('section-dialog').close();});
$('toggle-lock').onclick=()=>run('Updating section lock…',async()=>{const section=state.project.arrangement.sections.find(s=>s.id===state.section);state.project=await api(`/api/projects/${currentId()}/lock`,{section_id:state.section,locked:!section.locked,revision:state.project.revision});$('section-dialog').close();renderProject();toast(section.locked?'Section unlocked.':'Section locked.');});
$('update-timing').onclick=()=>run('Recalculating timing and analysis…',async()=>{state.project=await api(`/api/projects/${currentId()}/analyze`,{revision:state.project.revision,bpm:Number($('bpm').value),offset_seconds:Number($('offset').value)});renderProject();toast('Grid updated. Existing authored notes were preserved.');});
$('confirm-timing').onclick=()=>run('Recording timing review…',async()=>{state.project=await api(`/api/projects/${currentId()}/review`,{revision:state.project.revision,timing_reviewed:!state.project.project.timing_reviewed});renderProject();toast('Timing review status saved for this revision.');});
$('restore-version').onclick=()=>run('Restoring a saved arrangement…',async()=>{state.project=await api(`/api/projects/${currentId()}/restore`,{revision:state.project.revision,restore_revision:$('history').value});renderProject();toast('Saved version restored. Current locks were respected.');});
$('export-map').onclick=()=>run('Checking assets and building the map ZIP…',async()=>{const result=await api(`/api/projects/${currentId()}/export`,{});const link=document.createElement('a');link.href=result.url;link.download=result.filename;link.click();toast('Map exported. Preview in ArcViewer, then verify timing in Beat Saber.');});
$('fetch-map').onclick=()=>run('Fetching the exact BeatSaver version…',async()=>{await api('/api/corpus/fetch',{hash:$('map-hash').value.trim()});await renderCorpus();toast('Exact version downloaded and recorded.');});
$('import-archive').onclick=()=>$('archive-file').click();$('archive-file').onchange=()=>run('Importing the map archive…',async()=>{const file=$('archive-file').files[0];if(!file)return;if(file.size>64*1048576)throw new Error('Archive exceeds the 64 MB budget');await api('/api/corpus/import',{filename:file.name,archive:await fileBase64(file)});await renderCorpus();toast('Local map archive imported.');});
$('process-corpus').onclick=()=>run('Extracting contextual phrases…',async()=>{await api('/api/corpus/process',{});await renderCorpus();toast('Pattern extraction finished. Unsupported sources are reported.');});
$('retrieve').onclick=()=>run('Finding diverse phrases…',async()=>renderPatterns(await api('/api/corpus/retrieve',{bpm:Number($('retrieval-bpm').value),limit:12,project_id:state.project?.project.id})));
$('show-workspace').onclick=()=>toast(`Workspace: ${state.workspace}. All project artifacts are ordinary local files.`);
$('open-playtest').onclick=()=>{$('game-build').value=state.project.project.game_build||'';$('playtest-dialog').showModal();};$('close-playtest').onclick=()=>$('playtest-dialog').close();
$('playtest-form').onsubmit=e=>{e.preventDefault();run('Saving your playtest observations…',async()=>{state.project=await api(`/api/projects/${currentId()}/review`,{revision:state.project.revision,playtested:true,game_build:$('game-build').value,minutes_spent:Number($('review-minutes').value),variant:$('review-variant').value,decision:$('review-decision').value,notes:$('review-notes').value,ratings:{enjoyment:Number($('rating-enjoyment').value),technical_interest:Number($('rating-tech').value),fatigue:Number($('rating-fatigue').value),timing:Number($('rating-timing').value)}});$('playtest-dialog').close();renderProject();toast('Playtest saved with this arrangement revision and exact audio hash.');});};
window.addEventListener('resize',drawWaveform);document.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','TEXTAREA','SELECT','BUTTON'].includes(e.target.tagName)&&state.project&&state.view==='studio'){e.preventDefault();$('play').click();}});
(async()=>{try{const info=await api('/api/status');state.token=info.token;state.workspace=info.workspace;const list=await refreshProjects();if(list.length)await loadProject(list[0].id);}catch(e){toast(e.message,true);}})();

$('preview-map').onclick=()=>{
  if(state.busy){toast('Please wait for the current operation to finish.');return;}
  const projectId=currentId(), revision=state.project.revision, seconds=$('audio').currentTime;
  const viewer=window.open('about:blank','_blank');
  if(viewer){viewer.opener=null;viewer.document.title='Preparing ArcViewer';viewer.document.body.textContent='Preparing your saved map for ArcViewer...';}
  $('audio').pause();
  run('Preparing 3D preview...',async()=>{
    try{
      const result=await api(`/api/projects/${projectId}/preview`,{revision,seconds});
      $('arcviewer-open').href=result.viewer_url;
      $('arcviewer-download').href=result.url;
      $('arcviewer-download').download=result.filename;
      $('arcviewer-handoff').hidden=false;
      if(viewer && !viewer.closed)viewer.location.replace(result.viewer_url);
      else toast('Preview ready. Select Open ArcViewer above to continue.');
    }catch(error){if(viewer && !viewer.closed)viewer.close();throw error;}
  });
};
