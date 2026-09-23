'use strict';
const $ = id => document.getElementById(id);
const state = {token: '', project: null, view: 'studio', section: null, zoom: 24, selection: [0, 8], busy: false};
const arrows = ['↑', '↓', '←', '→', '↖', '↗', '↙', '↘', '●'];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = seconds => `${Math.floor(Math.max(0,seconds)/60)}:${String(Math.floor(Math.max(0,seconds)%60)).padStart(2,'0')}`;
const clock = seconds => `${time(seconds)}.${Math.floor(Math.max(0,Number(seconds)||0)*10)%10}`;
function toast(message, error = false) { $('toast').textContent = message; $('toast').className = error ? 'error' : ''; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, error ? 10000 : 5000); }
// The studio swaps in updated code between requests; a refused connection during that second is retried.
async function reach(path, options) {
  for (let attempt = 0; ; attempt++) {
    try { return await fetch(path, options); }
    catch (error) { if (attempt >= 20) throw error; await new Promise(done => setTimeout(done, 500)); }
  }
}
async function api(path, data) {
  const response = await reach(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-SaberMapper-Token':state.token},body:JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) {
    const e=value.error, error=new Error((typeof e==='string'?e:e?.message)||`Request failed (${response.status})`);
    if (e && typeof e==='object') Object.assign(error,{code:e.code,details:e.details,fix:e.fix});
    error.status=response.status; throw error;
  }
  return value;
}
async function run(label, callback) {
  if (state.busy) { toast('Still working…'); return; }
  state.busy = true; $('busy-text').textContent = label; $('busy').hidden = false;
  try { return await callback(); } catch (error) { toast(error.message, true); } finally { state.busy = false; $('busy').hidden = true; }
}
function download(name, data, type='application/json') {
  const url = URL.createObjectURL(new Blob([typeof data === 'string' ? data : JSON.stringify(data,null,2)],{type}));
  const link = document.createElement('a'); link.href=url; link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function fileBase64(file) { return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Could not read the file'));reader.readAsDataURL(file);}); }
function currentId() { if (!state.project) throw new Error('Open a project first'); return state.project.project.id; }
function scoped(data) { return {...data, difficulty: state.project.difficulty}; }
function projectUrl(id, difficulty) { return `/api/projects/${id}${difficulty ? `?difficulty=${encodeURIComponent(difficulty)}` : ''}`; }
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
const byName = (a,b) => a.localeCompare(b,undefined,{sensitivity:'base',numeric:true});
const shortDate = iso => { const d=new Date(iso); if (!iso || isNaN(d)) return ''; const p=n=>String(n).padStart(2,'0'); return `${p(d.getMonth()+1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
const collapsedGroups = (() => { try { return new Set(JSON.parse(localStorage.getItem('sabermapper.collapsed') || '[]')); } catch { return new Set(); } })();
function projectTree(projects) {
  const artists=new Map();
  for (const p of projects) {
    const artist=(p.artist||'').trim()||'Unknown artist', album=(p.album||'').trim();
    if (!artists.has(artist)) artists.set(artist,new Map());
    const albums=artists.get(artist); if (!albums.has(album)) albums.set(album,[]); albums.get(album).push(p);
  }
  const song=p=>`<button class="project-link ${state.project?.project.id===p.id?'active':''}" data-project="${esc(p.id)}" title="${esc(p.title)} · updated ${esc(shortDate(p.updated_at))}"><span>${esc(p.title)}</span><small>${esc(shortDate(p.updated_at))}</small></button>`;
  const songs=list=>list.slice().sort((a,b)=>byName(a.title||'',b.title||'')).map(song).join('');
  const group=(key,cls,label,body)=>`<details class="${cls}" data-group="${esc(key)}" ${collapsedGroups.has(key)?'':'open'}><summary title="${esc(label)}">${esc(label)}</summary>${body}</details>`;
  return [...artists.keys()].sort(byName).map(artist=>{
    const albums=artists.get(artist), named=[...albums.keys()].filter(Boolean).sort(byName);
    return group(`artist:${artist}`,'tree-artist',artist,
      named.map(album=>group(`album:${artist}\n${album}`,'tree-album',album,songs(albums.get(album)))).join('')+songs(albums.get('')||[]));
  }).join('');
}
async function refreshProjects() {
  const projects=await api('/api/projects');
  $('project-list').innerHTML=projects.length?projectTree(projects):'<p class="hint">No projects yet.</p>';
  $('project-list').querySelectorAll('[data-project]').forEach(b=>b.onclick=()=>run('Opening…',()=>loadProject(b.dataset.project)));
  $('project-list').querySelectorAll('[data-group]').forEach(d=>d.ontoggle=()=>{d.open?collapsedGroups.delete(d.dataset.group):collapsedGroups.add(d.dataset.group);try{localStorage.setItem('sabermapper.collapsed',JSON.stringify([...collapsedGroups]));}catch{}});
  return projects;
}
async function loadProject(id, difficulty) { $('arcviewer-handoff').hidden=true; state.project=await api(projectUrl(id, difficulty)); state.selection=[0,Math.min(8,totalBeats())]; showView('studio'); renderProject(true);await refreshProjects(); }
function showView(view) { state.view=view;document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==`view-${view}`);document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));$('view-label').textContent=({studio:'Studio',corpus:'Patterns',research:'Research'}[view]);if(view==='corpus')run('Loading…',renderCorpus);if(view==='research')run('Loading…',renderResearch);if(view==='studio' && state.project)requestAnimationFrame(drawWaveform); }
function renderProject(audioChanged=false) {
  const d=state.project,a=d.arrangement;
  $('welcome').hidden=true;$('project-view').hidden=false;
  $('project-title').textContent=a.song.title;$('project-subtitle').textContent=`${a.song.artist} · ${a.difficulty.name}${a.difficulty.target_tier?` · target ${a.difficulty.target_tier.replaceAll('_',' ')}`:''}`;
  $('difficulty-select').innerHTML=(d.difficulties||[]).map(x=>`<option value="${esc(x.name)}" ${x.name===d.difficulty?'selected':''}>${esc(x.name)}${x.target_tier?` · ${esc(x.target_tier.replaceAll('_',' '))}`:''}${x.nps!==null?` · ${x.nps} nps`:''}</option>`).join('');
  $('project-origin').textContent=d.project.origin==='original-demo'?'DEMO':'TRACK';
  $('stat-bpm').textContent=Number(a.song.bpm.toFixed(2));$('stat-duration').textContent=time(d.project.duration_seconds);$('stat-notes').textContent=d.notes.length;
  $('stat-density').textContent=`${(d.notes.length/d.project.duration_seconds).toFixed(2)} notes/sec`;
  const errors=d.diagnostics.filter(x=>x.severity==='error'), warnings=d.diagnostics.filter(x=>x.severity==='warning');
  $('stat-checks').textContent=errors.length?`${errors.length} errors`:warnings.length?`${warnings.length} warnings`:'OK';$('stat-check-detail').textContent=errors.length||warnings.length?'see Checks':'no issues';
  $('bpm').value=a.song.bpm;$('offset').value=a.song.audio_offset_seconds;$('timing-badge').textContent=d.project.timing_reviewed?'Checked':'Unchecked';$('timing-badge').className='badge '+(d.project.timing_reviewed?'good':'warn');$('confirm-timing').textContent=d.project.timing_reviewed?'Unmark':'Mark checked \u2713';
  const timing=d.analysis.timing||{};$('timing-confidence').textContent=`${timing.source || 'Auto-detected'}${timing.confidence !== undefined ? ` \u00b7 confidence ${typeof timing.confidence==='number' ? timing.confidence.toFixed(2) : timing.confidence}` : ''}`;
  $('sections').innerHTML=a.sections.map(s=>`<button class="section-card" data-section="${esc(s.id)}"><div class="name"><span>${esc(s.id)}</span><span>${s.locked?'▣':s.resolved?'↗':'?'}</span></div><div class="intent">${esc(s.intent)}</div><div class="meta">BEATS ${esc(s.start_beat)}–${beatNumber(s.start_beat)+beatNumber(s.length_beats)} · ${s.notes.length} notes${s.patterns.length?' · '+s.patterns.length+' patterns':''}</div></button>`).join('');
  $('sections').querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>openSection(b.dataset.section));
  $('section-strip').innerHTML=a.sections.map(s=>`<button data-seek="${beatNumber(s.start_beat)}" title="${esc(s.intent)}">${esc(s.id)}</button>`).join('');
  $('section-strip').querySelectorAll('[data-seek]').forEach(b=>b.onclick=()=>{$('audio').currentTime=beatSeconds(Number(b.dataset.seek));state.selection=[Number(b.dataset.seek),Number(b.dataset.seek)+8];drawTimeline();});
  $('diagnostic-count').textContent=d.diagnostics.length;
  $('diagnostics').innerHTML=d.diagnostics.length?d.diagnostics.map(x=>`<div class="diagnostic ${esc(x.severity)}"><strong>${esc(x.code.replaceAll('_',' '))}</strong><br>${esc(x.message)}${x.section_id?`<br><small>${esc(x.section_id)}</small>`:''}</div>`).join(''):'<div class="diagnostic good">✓ No issues.</div>';
  const metrics=Object.entries(d.movement.metrics||{}).filter(([,v])=>typeof v==='number').slice(0,7);
  $('movement').innerHTML=metrics.length?metrics.map(([k,v])=>`<div><span>${esc(k.replaceAll('_',' '))}</span><strong>${Number(v.toFixed(2))}</strong></div>`).join(''):'<div>No notes yet.</div>';
  $('feedback-list').innerHTML=d.feedback.map(f=>`<div class="feedback-item"><small>${f.kind==='note'?`NOTE ${esc(clock(f.song_time))} · BEAT ${esc(f.beat)}${f.section?` · ${esc(f.section)}`:''}${f.stale?' · older revision':''}`:`BEATS ${esc(f.start_beat)}–${esc(f.end_beat)} · ${(f.object_ids||[]).length} notes`} · ${esc(String(f.revision||'').slice(0,8))} <a href="/api/projects/${currentId()}/files/feedback/${f.id}.json" download>JSON ↓</a></small><p>${esc(f.text)}</p></div>`).join('');
  $('history').innerHTML=d.history.map(h=>`<option value="${h}" ${h===d.revision?'selected':''}>${h.slice(0,12)} ${h===d.revision?'· current':''}</option>`).join('');
  $('review-count').textContent=(d.reviews||[]).filter(r=>r.playtested).length;
  $('arrangement-editor').value=JSON.stringify(a,null,2);$('editor-state').textContent=`Saved ${d.revision.slice(0,10)}`;
  if(audioChanged){$('audio').src=`/api/projects/${d.project.id}/files/song.ogg`;$('play').textContent='▶';$('play').setAttribute('aria-label','Play');}
  renderMusicRuns(audioChanged);drawTimeline();requestAnimationFrame(drawWaveform);renderStage();renderConsole();
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
  for(const wall of beatmap.obstacles||[]){parts.push(`<rect x="${left+wall.b*z}" y="${42+wall.x*62}" width="${Math.max(2,wall.d*z)}" height="${Math.min(wall.w,4-wall.x)*62}" fill="#8093aa" fill-opacity="0.13" stroke="#6c7d93" stroke-dasharray="4 3"><title>Wall · beat ${wall.b} · ${wall.d} beats</title></rect>`);}
  for(const bomb of beatmap.bombNotes||[]){const x=left+bomb.b*z,y=42+bomb.x*62+(2-bomb.y)*18+12;parts.push(`<circle cx="${x}" cy="${y}" r="6" fill="#b3bfd0"/><text x="${x}" y="${y+3}" text-anchor="middle" fill="#152032" font-size="10">×</text>`);}
  for(const obj of [...(beatmap.sliders||[]),...(beatmap.burstSliders||[])]){const x=left+obj.b*z,tx=left+obj.tb*z,y=42+obj.x*62+(2-obj.y)*18+12,ty=42+obj.tx*62+(2-obj.ty)*18+12;parts.push(`<path d="M${x},${y} C${(x+tx)/2},${y} ${(x+tx)/2},${ty} ${tx},${ty}" fill="none" stroke="${obj.c===0?'#f77a92':'#62c8ed'}" stroke-opacity="0.5" stroke-width="2"/>`);}
  const flagged=new Set(state.project.diagnostics.flatMap(d=>d.object_ids||[]));
  for(const n of notes){const x=left+n.beat*z,y=42+n.x*62+(2-n.y)*18+12,color=n.color===0?'#f77a92':'#62c8ed',selected=n.beat>=start&&n.beat<end;parts.push(`<g data-note="${esc(n.id)}"><rect x="${x-7}" y="${y-7}" width="14" height="14" rx="3" fill="${color}" fill-opacity="${selected?1:0.65}" stroke="${flagged.has(n.id)?'#f4c776':'none'}" stroke-width="2"/><text x="${x}" y="${y+4}" text-anchor="middle" fill="#101827" font-size="11" font-family="sans-serif" font-weight="bold" pointer-events="none">${arrows[n.direction]}</text><title>${esc(n.id)} · beat ${n.beat} · row ${n.y} · ${n.color===0?'left':'right'} hand</title></g>`);}
  parts.push(`<line id="playhead" x1="${left}" y1="26" x2="${left}" y2="291" stroke="#b9f18d" stroke-width="1.5"/><text x="${left}" y="309" fill="#526b85" font-size="8" font-family="sans-serif">BEATS → · rows top / middle / bottom per lane</text>`);
  svg.innerHTML=parts.join('');$('range-start').value=start;$('range-end').value=end;$('selected-count').textContent=`${notes.filter(n=>n.beat>=start&&n.beat<end).length} notes`;updatePlayhead();drawMusicLanes();
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
function openSection(id){state.section=id;const section=state.project.arrangement.sections.find(s=>s.id===id);$('section-title').textContent=id;$('section-editor').value=JSON.stringify(section,null,2);$('section-editor').readOnly=section.locked;$('save-section').disabled=section.locked;$('toggle-lock').textContent=section.locked?'Unlock':'Lock';$('section-dialog').showModal();}
async function saveArrangement(arrangement){state.project=await api(`/api/projects/${currentId()}/save`,scoped({arrangement,revision:state.project.revision}));renderProject();await refreshProjects();toast('Saved.');}
async function renderCorpus(){const data=await api('/api/corpus');$('corpus-summary').innerHTML=`<div><span>MAPS</span><strong>${data.rows.length}</strong></div><div><span>PHRASES</span><strong>${data.pattern_count}</strong></div><div><span>FAMILIES</span><strong>${data.group_count ?? data.groups.length}</strong></div><div><span>STORAGE</span><strong>${((data.report.archive_bytes||0)/1048576).toFixed(1)}</strong><small>MB</small></div>`;$('corpus-rows').innerHTML=data.rows.length?`<table><thead><tr><th>Version</th><th>Status</th><th>Size</th><th>Audio</th></tr></thead><tbody>${data.rows.map(r=>`<tr><td title="${esc(r.version_hash)}">${esc(r.version_hash.slice(0,16))}…</td><td>${esc(r.status)}${r.error?`<br><small>${esc(r.error)}</small>`:''}</td><td>${((r.archive_bytes||0)/1048576).toFixed(1)} MB</td><td>${r.retain_audio?'Kept':'Features only'}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">No maps yet. Import a ZIP or fetch a BeatSaver hash.</div>';renderPatterns(data.patterns.slice(0,12).map(pattern=>({pattern,reason:'From source map'})));}
function renderPatterns(items){$('pattern-results').innerHTML=items.length?items.map((item,i)=>{const p=item.pattern;return `<article class="pattern-card"><h3>${esc(p.difficulty)} · ${p.length_beats} beats</h3><div>${p.note_count} notes · ${p.nps} NPS · ${p.bpm} BPM</div><small>${esc(item.reason)}</small><small>SOURCE ${esc(p.version_hash.slice(0,12))} · BEAT ${p.start_beat}</small><button class="text-button" data-pattern="${i}">JSON ↓</button></article>`;}).join(''):'<div class="empty">No matching phrases. The current song is excluded.</div>';$('pattern-results').querySelectorAll('[data-pattern]').forEach(b=>b.onclick=()=>run('Loading\u2026',async()=>{const p=items[Number(b.dataset.pattern)].pattern;download(`phrase-${b.dataset.pattern}.json`,p.notes?p:await api('/api/corpus/pattern',{id:p.id}));}));}
async function renderResearch(){const data=await api('/api/research'),profile=data.profile,notes=(data.knowledge.notes||[]);$('research-content').innerHTML=`<div class="research-grid"><div class="panel"><div class="panel-head"><h2>Player</h2></div><div class="knowledge-note"><p>${esc(profile.summary||'Past ScoreSaber and BeatLeader scores.')}</p><pre class="profile-data">${esc(JSON.stringify(profile.statistics||profile,null,2))}</pre></div></div></div><div class="panel research-notes"><div class="panel-head"><h2>Mapping notes</h2></div>${notes.length?notes.map(n=>`<article class="knowledge-note"><h3>${esc(n.title)}</h3><p>${esc(n.summary)}</p><a href="${esc(n.source)}" target="_blank" rel="noreferrer">Source ↗</a></article>`).join(''):'<p class="empty">No notes.</p>'}</div>`;}

document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));
$('new-project').onclick=$('welcome-import').onclick=()=>$('import-dialog').showModal();$('close-import').onclick=()=>$('import-dialog').close();$('close-section').onclick=()=>$('section-dialog').close();
$('create-demo').onclick=()=>run('Creating demo…',async()=>{state.project=await api('/api/demo',{});renderProject(true);await refreshProjects();toast('Demo ready.');});
$('audio-file').onchange=()=>{if(!$('import-title').value)$('import-title').value=$('audio-file').files[0]?.name.replace(/\.[^.]+$/,'')||'';};
$('import-form').onsubmit=e=>{e.preventDefault();run('Importing…',async()=>{const file=$('audio-file').files[0];if(!file)throw new Error('Choose an audio file');if(file.size>64*1048576)throw new Error('File is over 64 MB');const data={filename:file.name,audio:await fileBase64(file),title:$('import-title').value,artist:$('import-artist').value,album:$('import-album').value,bpm:$('import-bpm').value||null};state.project=await api('/api/projects/import',data);$('import-dialog').close();showView('studio');renderProject(true);await refreshProjects();toast('Imported. Check the timing.');});};
$('play').onclick=async()=>{const audio=$('audio');try{if(audio.paused)await audio.play();else audio.pause();}catch(e){toast(`Playback failed: ${e.message}`,true);}};
$('audio').onplay=()=>{$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','Pause');};$('audio').onpause=()=>{$('play').textContent='▶';$('play').setAttribute('aria-label','Play');};$('audio').ontimeupdate=()=>{updatePlayhead();drawWaveform();};$('audio').onloadedmetadata=updatePlayhead;$('speed').onchange=()=>$('audio').playbackRate=Number($('speed').value);$('zoom').oninput=drawTimeline;
$('waveform').onclick=e=>{if(!state.project)return;const r=e.currentTarget.getBoundingClientRect();$('audio').currentTime=(e.clientX-r.left)/r.width*state.project.project.duration_seconds;};
let dragStart=null;$('timeline').onpointerdown=e=>{if(!state.project)return;const r=e.currentTarget.getBoundingClientRect();dragStart=Math.max(0,Math.round((e.clientX-r.left-48)/Number($('zoom').value)*4)/4);e.currentTarget.setPointerCapture(e.pointerId);};$('timeline').onpointerup=e=>{if(dragStart===null)return;const r=e.currentTarget.getBoundingClientRect(),end=Math.max(0,Math.round((e.clientX-r.left-48)/Number($('zoom').value)*4)/4);state.selection=[Math.min(dragStart,end),Math.max(dragStart,end)+0.25];dragStart=null;drawTimeline();};
for(const id of ['range-start','range-end'])$(id).onchange=()=>{const a=Number($('range-start').value),b=Number($('range-end').value);if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b<=a){toast('End must be after start.',true);return;}state.selection=[a,b];drawTimeline();};
$('snapshot').onclick=()=>download('sabermapper-timeline.svg',new XMLSerializer().serializeToString($('timeline')),'image/svg+xml');
$('download-arrangement').onclick=()=>download(`${state.project.difficulty}.arrangement.json`,state.project.arrangement);
$('difficulty-select').onchange=()=>run('Opening…',async()=>{state.project=await api(projectUrl(currentId(),$('difficulty-select').value));renderProject();});
$('save-feedback').onclick=()=>run('Saving…',async()=>{await api(`/api/projects/${currentId()}/feedback`,scoped({revision:state.project.revision,start_beat:state.selection[0],end_beat:state.selection[1],text:$('feedback-text').value}));$('feedback-text').value='';state.project=await api(projectUrl(currentId(),state.project.difficulty));renderProject();toast('Feedback saved.');});
$('save-arrangement').onclick=()=>run('Saving…',()=>saveArrangement(JSON.parse($('arrangement-editor').value)));
$('arrangement-editor').oninput=()=>$('editor-state').textContent='Unsaved';$('reset-editor').onclick=()=>{$('arrangement-editor').value=JSON.stringify(state.project.arrangement,null,2);$('editor-state').textContent='Discarded';};
$('save-section').onclick=()=>run('Saving…',async()=>{const updated=JSON.parse($('section-editor').value);if(updated.id!==state.section)throw new Error('Section ID must not change');const arrangement=structuredClone(state.project.arrangement);arrangement.sections[arrangement.sections.findIndex(s=>s.id===state.section)]=updated;await saveArrangement(arrangement);$('section-dialog').close();});
$('toggle-lock').onclick=()=>run('Saving…',async()=>{const section=state.project.arrangement.sections.find(s=>s.id===state.section);state.project=await api(`/api/projects/${currentId()}/lock`,scoped({section_id:state.section,locked:!section.locked,revision:state.project.revision}));$('section-dialog').close();renderProject();toast(section.locked?'Unlocked.':'Locked.');});
$('update-timing').onclick=()=>run('Updating timing…',async()=>{state.project=await api(`/api/projects/${currentId()}/analyze`,scoped({revision:state.project.revision,bpm:Number($('bpm').value),offset_seconds:Number($('offset').value)}));renderProject();toast('Timing updated.');});
$('confirm-timing').onclick=()=>run('Saving…',async()=>{state.project=await api(`/api/projects/${currentId()}/review`,scoped({revision:state.project.revision,timing_reviewed:!state.project.project.timing_reviewed}));renderProject();toast('Saved.');});
$('restore-version').onclick=()=>run('Restoring…',async()=>{state.project=await api(`/api/projects/${currentId()}/restore`,scoped({revision:state.project.revision,restore_revision:$('history').value}));renderProject();toast('Version restored.');});
$('export-map').onclick=()=>run('Exporting…',async()=>{const result=await api(`/api/projects/${currentId()}/export`,{});const link=document.createElement('a');link.href=result.url;link.download=result.filename;link.click();toast('Exported.');});
$('fetch-map').onclick=()=>run('Fetching…',async()=>{await api('/api/corpus/fetch',{hash:$('map-hash').value.trim()});await renderCorpus();toast('Map fetched.');});
$('import-archive').onclick=()=>$('archive-file').click();$('archive-file').onchange=()=>run('Importing…',async()=>{const file=$('archive-file').files[0];if(!file)return;if(file.size>64*1048576)throw new Error('File is over 64 MB');await api('/api/corpus/import',{filename:file.name,archive:await fileBase64(file)});await renderCorpus();toast('Map imported.');});
$('process-corpus').onclick=()=>run('Extracting…',async()=>{await api('/api/corpus/process',{});await renderCorpus();toast('Patterns extracted.');});
$('retrieve').onclick=()=>run('Searching…',async()=>renderPatterns(await api('/api/corpus/retrieve',{bpm:Number($('retrieval-bpm').value),limit:12,project_id:state.project?.project.id})));
$('show-workspace').onclick=()=>toast(`Workspace: ${state.workspace}`);
$('open-playtest').onclick=()=>{$('game-build').value=state.project.project.game_build||'';$('playtest-dialog').showModal();};$('close-playtest').onclick=()=>$('playtest-dialog').close();
$('playtest-form').onsubmit=e=>{e.preventDefault();run('Saving…',async()=>{state.project=await api(`/api/projects/${currentId()}/review`,{difficulty:state.project.difficulty,revision:state.project.revision,playtested:true,game_build:$('game-build').value,minutes_spent:Number($('review-minutes').value),variant:$('review-variant').value,decision:$('review-decision').value,notes:$('review-notes').value,ratings:{enjoyment:Number($('rating-enjoyment').value),technical_interest:Number($('rating-tech').value),fatigue:Number($('rating-fatigue').value),timing:Number($('rating-timing').value)}});$('playtest-dialog').close();renderProject();toast('Playtest saved.');});};
window.addEventListener('resize',drawWaveform);document.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','TEXTAREA','SELECT','BUTTON'].includes(e.target.tagName)&&state.project&&state.view==='studio'){e.preventDefault();$('play').click();}});
(async()=>{try{const info=await api('/api/status');state.token=info.token;state.workspace=info.workspace;state.code=info.code?.version;setInterval(checkCode,30000);const list=await refreshProjects();if(list.length)await loadProject(list[0].id);}catch(e){toast(e.message,true);}})();

// The viewer tab boots ArcViewer while the server writes the map ZIP; ArcViewer's map request waits for it.
$('preview-map').onclick=()=>{
  if(state.busy){toast('Still working…');return;}
  if(state.previewing){toast('The 3D preview is still exporting…');return;}
  const projectId=currentId(), revision=state.project.revision, difficulty=state.project.difficulty, seconds=$('audio').currentTime;
  const viewer=window.open('about:blank','_blank');
  if(viewer){viewer.opener=null;viewer.document.title='ArcViewer';viewer.document.body.textContent='Loading…';}
  $('audio').pause();
  run('Preparing preview…',async()=>{
    let result;
    try{
      result=await api(`/api/projects/${projectId}/preview`,{revision,seconds,difficulty});
      if(viewer && !viewer.closed)viewer.location.replace(result.viewer_url);
    }catch(error){if(viewer && !viewer.closed)viewer.close();throw error;}
    state.previewing=true;
    (async()=>{
      try{
        await api(result.status_url);
        $('arcviewer-open').href=result.viewer_url;
        $('arcviewer-download').href=result.url;
        $('arcviewer-download').download=result.filename;
        $('arcviewer-handoff').hidden=false;
        if(!viewer || viewer.closed)toast('Preview ready. Click Open ArcViewer.');
      }catch(error){if(viewer && !viewer.closed)viewer.close();toast(error.message,true);}
      finally{state.previewing=false;}
    })();
  });
};

// Verification console: play the chosen revision in Beat Saber, scrub, and leave timestamped notes.
// Every control calls the same HTTP API as the agent's CLI twins (`game ...`, `project feedback add|list`).
const verify={status:null,poll:null,dragging:false,seekTimer:null,noteTime:null,pending:null,key:''};
function verifyRevision(){return $('verify-revision').value||state.project.revision;}
function sliderSeconds(){return Number($('song-slider').value)||0;}
function gameActive(){const s=verify.status;return !!(s&&s.running&&s.bridge&&s.bridge.level);}
function consoleActive(){return !!state.project&&state.view==='studio'&&!document.hidden&&!$('project-view').hidden;}
function sectionAt(seconds){const beat=secondsBeat(seconds);return {beat,section:state.project.arrangement.sections.find(s=>beat>=beatNumber(s.start_beat)&&beat<beatNumber(s.start_beat)+beatNumber(s.length_beats))};}
function projectMoments(d){
  const raw=d.moments??d.project?.moments??d.analysis?.moments, list=Array.isArray(raw)?raw:Array.isArray(raw?.moments)?raw.moments:[];
  return list.map(m=>{const beat=m.beat??m.start_beat,seconds=Number(m.seconds??m.song_time??m.time??m.start_seconds??(beat!=null?beatSeconds(beatNumber(beat)):NaN));return {seconds,label:m.label||m.name||m.kind||m.type||'Key moment'};}).filter(m=>Number.isFinite(m.seconds));
}
function revisionNotes(){const d=state.project,revision=verifyRevision();return d.feedback.filter(f=>f.kind==='note'&&f.difficulty===d.difficulty&&f.revision===revision).sort((a,b)=>a.song_time-b.song_time);}
function renderConsole(){
  const d=state.project,duration=d.project.duration_seconds,key=`${d.project.id}/${d.difficulty}`,previous=$('verify-revision').value;
  const revisions=[d.revision,...d.history.filter(h=>h!==d.revision)];
  $('verify-revision').innerHTML=revisions.map(h=>`<option value="${esc(h)}">${esc(h.slice(0,10))}${h===d.revision?' · current':''}</option>`).join('');
  $('verify-revision').value=key===verify.key&&revisions.includes(previous)?previous:d.revision;
  $('song-slider').max=String(duration);$('slider-duration').textContent=time(duration);
  if(key!==verify.key){verify.key=key;setSlider(0);closeNote();refreshGame();}
  renderMarkers();
}
function renderMarkers(){
  const d=state.project,duration=d.project.duration_seconds||1;
  const sections=d.arrangement.sections.map(s=>{const seconds=beatSeconds(beatNumber(s.start_beat));return `<span class="marker-section" data-at="${seconds}" title="${esc(s.id)} · ${esc(time(seconds))} · ${esc(s.intent)}"></span>`;});
  const moments=projectMoments(d).map(m=>`<span class="marker-moment" data-at="${m.seconds}" title="${esc(m.label)} · ${esc(time(m.seconds))}"></span>`);
  const notes=revisionNotes();
  const pins=notes.map(n=>`<button type="button" class="marker-note${n.stale?' stale':''}" data-at="${n.song_time}" data-jump="${n.song_time}" aria-label="Note at ${esc(clock(n.song_time))}: ${esc(n.text)}" title="${esc(clock(n.song_time))} · ${esc(n.text)}"></button>`);
  const box=$('slider-markers');box.innerHTML=[...sections,...moments,...pins].join('');
  // style-src 'self' blocks style attributes in markup; positions are set through the CSSOM instead.
  box.querySelectorAll('[data-at]').forEach(el=>el.style.left=`${Math.min(100,Math.max(0,Number(el.dataset.at)/duration*100)).toFixed(3)}%`);
  $('note-list').innerHTML=notes.length?notes.map(n=>`<div class="feedback-item"><small><button type="button" data-jump="${n.song_time}">${esc(clock(n.song_time))} ↦</button> · BEAT ${esc(n.beat)}${n.section?` · ${esc(n.section)}`:''} · ${esc(n.source)}${n.stale?' · older revision':''}</small><p>${esc(n.text)}</p></div>`).join(''):'<p class="hint">No notes on this revision yet. Press Note (N) while playing.</p>';
  document.querySelectorAll('#slider-markers [data-jump], #note-list [data-jump]').forEach(b=>b.onclick=()=>jumpTo(Number(b.dataset.jump)));
}
function setSlider(seconds){$('song-slider').value=String(seconds);$('slider-time').textContent=time(seconds);}
function jumpTo(seconds){setSlider(seconds);if(gameActive())gameCall('seek',{seconds});else $('audio').currentTime=seconds;}
function leaseText(s){
  if(!s)return ['Game: checking…',''];
  if(!s.available)return ['Game bridge missing','missing'];
  const lease=s.lease;
  if(!lease)return [s.running?'Game running · no lease':'Game free',''];
  if(lease.holder_kind==='human')return ['Game: you (studio)','you'];
  return [`Agent: ${lease.holder||'unknown'}${lease.purpose?` · ${lease.purpose}`:''}`,'agent'];
}
function renderGame(){
  const s=verify.status,[label,kind]=leaseText(s),indicator=$('lease-indicator');
  indicator.textContent=label;indicator.className=`badge ${kind}`;
  const bridge=s?.bridge,level=bridge?.level;
  let line='';
  if(s?.error)line=`${s.error.message||s.error.code}${s.error.fix?` — ${s.error.fix}`:''}`;
  else if(level)line=`In game · ${level.difficulty||''} ${bridge.paused?'paused':'playing'} · ${clock(bridge.song_time||0)} / ${time(bridge.song_length||state.project?.project.duration_seconds||0)}${bridge.speed&&bridge.speed!==1?` · ${bridge.speed}×`:''}${bridge.fps?` · ${Math.round(bridge.fps)} fps`:''}`;
  else if(s?.running)line=`Beat Saber is running${bridge?.scene?` (${bridge.scene})`:''}; no level loaded.`;
  else if(s)line='Beat Saber is not running. Play in game starts it.';
  $('game-status').textContent=line;
  for(const id of ['game-pause','game-resume','game-restart'])$(id).disabled=!gameActive();
  for(const id of ['game-play-start','game-play-playhead','game-watch'])$(id).disabled=s?.available===false;
  if(gameActive()&&!verify.dragging&&Number.isFinite(bridge.song_time))setSlider(bridge.song_time);
}
async function refreshGame(){
  clearTimeout(verify.poll);
  try{verify.status=await api('/api/game/status');}catch(e){verify.status={available:true,running:false,lease:null,bridge:null,error:{message:e.message}};}
  renderGame();
  // Poll fast only while the console is visible and the game runs; otherwise refresh on focus and after actions.
  if(verify.status.running&&consoleActive())verify.poll=setTimeout(refreshGame,400);
}
function gameError(error){$('game-status').textContent=`${error.message}${error.fix?` — ${error.fix}`:''}`;toast(error.message,true);}
async function gameCall(action,body={}){try{const result=await api(`/api/game/${action}`,body);await refreshGame();return result;}catch(error){gameError(error);}}
function playInGame(seconds,mode='play',confirm=false){
  if(!state.project)return;
  const body={project:currentId(),revision:verifyRevision(),difficulty:state.project.difficulty,seconds,mode,...(confirm?{confirm_preempt:true}:{})};
  return run(mode==='watch'?'Starting Watch…':'Starting the game…',async()=>{
    let result;
    try{result=await api('/api/game/play',body);}
    catch(error){
      if(error.code==='game_busy'&&error.details?.preemptable){verify.pending=()=>playInGame(seconds,mode,true);$('preempt-message').textContent=error.message;$('preempt-dialog').showModal();return;}
      gameError(error);return;
    }
    $('audio').pause();
    if(result&&result.watch==='unavailable'){const why=result.message||result.reason||'ghost autoplay is not built yet';$('game-status').textContent=`Watch is not available yet: ${why}.`;toast('Watch is not available yet.');}
    else toast(`${mode==='watch'?'Watching':'Playing'} ${body.revision.slice(0,8)} in game from ${time(seconds)}.`);
    await refreshGame();
  });
}
function openNote(){
  if(!state.project)return;
  const duration=state.project.project.duration_seconds,live=gameActive()&&Number.isFinite(verify.status.bridge.song_time);
  verify.noteTime=Math.min(duration,Math.max(0,live?verify.status.bridge.song_time:sliderSeconds()));
  const {beat,section}=sectionAt(verify.noteTime);
  $('note-time').textContent=clock(verify.noteTime);$('note-where').textContent=`beat ${beat.toFixed(2)}${section?` · ${section.id}`:''} · revision ${verifyRevision().slice(0,8)}`;
  $('note-form').hidden=false;$('note-text').focus();
}
function closeNote(){$('note-form').hidden=true;$('note-text').value='';verify.noteTime=null;}
$('game-play-start').onclick=()=>playInGame(0);
$('game-play-playhead').onclick=()=>playInGame(sliderSeconds());
$('game-watch').onclick=()=>playInGame(sliderSeconds(),'watch');
$('game-pause').onclick=()=>gameCall('pause');$('game-resume').onclick=()=>gameCall('resume');$('game-restart').onclick=()=>gameCall('restart');
$('verify-revision').onchange=()=>{closeNote();renderMarkers();};
$('song-slider').addEventListener('input',()=>{
  verify.dragging=true;const seconds=sliderSeconds();$('slider-time').textContent=time(seconds);
  if(!gameActive())$('audio').currentTime=seconds;
  clearTimeout(verify.seekTimer);
  verify.seekTimer=setTimeout(()=>{verify.dragging=false;if(gameActive())gameCall('seek',{seconds:sliderSeconds()});},300);
});
$('audio').addEventListener('timeupdate',()=>{if(state.project&&!gameActive()&&!verify.dragging)setSlider($('audio').currentTime);});
$('note-button').onclick=openNote;$('note-cancel').onclick=closeNote;
$('note-text').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();closeNote();}else if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();$('note-form').requestSubmit();}});
$('note-form').onsubmit=e=>{e.preventDefault();const seconds=verify.noteTime,revision=verifyRevision();if(seconds===null)return;run('Saving note…',async()=>{
  const note=await api(`/api/projects/${currentId()}/note`,{song_time:seconds,text:$('note-text').value,revision,difficulty:state.project.difficulty});
  closeNote();state.project=await api(projectUrl(currentId(),state.project.difficulty));renderProject();$('verify-revision').value=revision;renderMarkers();
  toast(`Note saved at ${clock(note.song_time)} · beat ${note.beat}${note.section?` · ${note.section}`:''}${note.stale?' (older revision)':''}.`);
});};
$('confirm-preempt').onclick=()=>{$('preempt-dialog').close();const next=verify.pending;verify.pending=null;if(next)next();};
$('cancel-preempt').onclick=$('close-preempt').onclick=()=>{verify.pending=null;$('preempt-dialog').close();};
document.addEventListener('keydown',e=>{if(e.key?.toLowerCase()==='n'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)&&!document.querySelector('dialog[open]')&&consoleActive()){e.preventDefault();openNote();}});
document.addEventListener('visibilitychange',()=>{if(consoleActive())refreshGame();});window.addEventListener('focus',()=>{if(consoleActive())refreshGame();});
// The server follows code updates; this page keeps its loaded code until the user reloads it.
async function checkCode(){
  if(!state.code)return;
  let code;try{code=(await api('/api/status')).code;}catch{return;}
  if(!code)return;
  const failed=code.update?.state==='failed', updated=code.version!==state.code;
  $('update-text').textContent=updated?'SaberMapper was updated. Reload this page when you are ready; ArcViewer tabs are not affected.'
    :failed?`An update could not load; the studio keeps running the previous code. ${code.update.error||''}`:'';
  $('update-reload').hidden=!updated;$('update-banner').classList.toggle('warn',failed&&!updated);$('update-banner').hidden=!(updated||failed);
}
$('update-reload').onclick=()=>location.reload();
document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkCode();});
