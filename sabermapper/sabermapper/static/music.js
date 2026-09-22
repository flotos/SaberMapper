'use strict';
// Evidence is read-only. The revision-aware arrangement editor stores agent focus.
let musicReport = null, musicRun = '', musicProject = '', musicRequest = 0;
function renderMusicRuns(reset=false) {
  if (reset) { musicReport=null;musicRun='';musicProject=currentId();musicRequest++;musicAudioRequest++; }
  const runs=state.project.musical_runs || [];
  $('music-run').innerHTML='<option value="">None</option>'+runs.map(r=>`<option value="${esc(r.id)}">${esc(r.backend)} / ${esc(r.preset)} / ${esc(r.created_at.slice(0,19))}</option>`).join('');
  $('music-run').value=musicRun;
  if(reset){$('music-listen').innerHTML='<option value="mix">Full mix</option>';$('music-download').hidden=true;$('music-status').textContent=runs.length?'Pick a run.':'No analysis yet.';}
  renderActiveFocus();
}
async function loadMusicRun() {
  const id=currentId(), selected=$('music-run').value, request=++musicRequest;
  const report=selected?await api(`/api/projects/${id}/files/musical/${selected}/report.json`):null;
  if(request!==musicRequest || id!==currentId())return;
  musicRun=selected;musicProject=id;musicReport=report;
  const layers=Object.entries(report?.layers||{}).filter(([,l])=>l.audio_file);
  $('music-listen').innerHTML='<option value="mix">Full mix</option>'+layers.map(([name])=>`<option value="${esc(name)}">${esc(name)} (solo)</option>`).join('');
  switchMusicAudio();
  $('music-download').hidden=!report;
  $('music-download').href=report?`/api/projects/${id}/files/musical/${selected}/report.json`:'';
  $('music-status').textContent=report?`${report.backend} · lines: spectral hits · dots: energy rises`:'Pick a run.';
  drawMusicLanes();
}
let musicAudioRequest=0;
function switchMusicAudio() {
  const player=$('audio'), seconds=player.currentTime, playing=!player.paused, request=++musicAudioRequest;
  const name=$('music-listen').value, file=musicReport?.layers[name]?.audio_file;
  const relative=file?`musical/${musicRun}/${file}`:'song.ogg';
  const url=`/api/projects/${currentId()}/files/${relative}`;
  if(player.getAttribute('src')===url)return;
  player.pause();
  player.addEventListener('loadedmetadata',async()=>{
    if(request!==musicAudioRequest)return;
    player.currentTime=Math.min(seconds,player.duration);player.playbackRate=Number($('speed').value);
    if(playing){try{await player.play();}catch(e){toast(e.message,true);}}
  },{once:true});
  player.src=url;
}
function drawMusicLanes() {
  const svg=$('music-lanes');if(!svg || !state.project)return;
  const report=musicProject===currentId()?musicReport:null, [start,end]=state.selection;
  const fromSeconds=beatSeconds(start), toSeconds=beatSeconds(end);
  const layers=Object.entries(report?.layers||{}), width=760,left=110,span=width-left-12,height=45+(layers.length+1)*38;
  svg.setAttribute('height',height);svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  let parts=[`<rect width="${width}" height="${height}" fill="#111720"/><text x="12" y="18" fill="#b9c7d8" font-size="11">Beats ${start}–${end}</text>`];
  const x=beat=>left+(beat-start)/(end-start)*span;
  for(let b=Math.ceil(start);b<end;b+=Math.max(1,Math.ceil((end-start)/24))){parts.push(`<line x1="${x(b)}" x2="${x(b)}" y1="26" y2="${height}" stroke="#263345"/><text x="${x(b)}" y="22" fill="#8193aa" font-size="10">${b}</text>`);}
  parts.push('<text x="10" y="51" fill="#b9c7d8" font-size="12">Notes</text>');
  for(const n of state.project.notes.filter(n=>n.beat>=start&&n.beat<end))parts.push(`<circle cx="${x(n.beat)}" cy="47" r="3" fill="${n.color===0?'#f77a92':'#62c8ed'}"/>`);
  layers.forEach(([name,layer],index)=>{
    const y=85+index*38;parts.push(`<text x="10" y="${y}" fill="#b9c7d8" font-size="12">${esc(name)}</text>`);
    for(const e of layer.events){if(e.seconds<fromSeconds||e.seconds>=toSeconds)continue;const beat=secondsBeat(e.seconds),px=x(beat),opacity=.2+.8*e.strength;parts.push(`<g data-seconds="${e.seconds}"><title>${esc(name)} · ${esc(e.method)} · ${e.seconds}s · strength ${e.strength}</title>${e.method==='spectral_flux'?`<line x1="${px}" x2="${px}" y1="${y-22*e.strength}" y2="${y+4}" stroke="#b9f18d" stroke-width="2" opacity="${opacity}"/>`:`<circle cx="${px}" cy="${y+7}" r="2.5" fill="#f4c776" opacity="${opacity}"/>`}</g>`);}
  });
  svg.innerHTML=parts.join('');
  svg.querySelectorAll('[data-seconds]').forEach(el=>el.onclick=()=>{$('audio').currentTime=Number(el.dataset.seconds);});
}
function renderActiveFocus() {
  if(!state.project)return;
  const beat=secondsBeat($('audio').currentTime);
  for(const section of state.project.arrangement.sections){const relative=beat-beatNumber(section.start_beat);for(const phrase of section.musical_focus||[]){if(relative>=beatNumber(phrase.start_beat)&&relative<beatNumber(phrase.end_beat)){
    $('active-focus').textContent=`Focus: ${phrase.lead==='mix'?'whole mix':phrase.lead} · ${Object.entries(phrase.weights).map(([name,w])=>`${name} ${Math.round(w*100)}%`).join(', ')} · ${phrase.intent}`;return;
  }}}
  $('active-focus').textContent='No focus here.';
}
$('audio').addEventListener('timeupdate',renderActiveFocus);
$('music-mute').onchange=()=>{$('audio').muted=$('music-mute').checked;};
$('music-listen').onchange=switchMusicAudio;
$('music-run').onchange=()=>run('Loading…',loadMusicRun);
$('analyze-music').onclick=()=>run('Analyzing…',async()=>{
  const result=await api(`/api/projects/${currentId()}/music`,{backend:$('music-backend').value,preset:$('music-preset').value});
  state.project.musical_runs=(await api(`/api/projects/${currentId()}`)).musical_runs;
  renderMusicRuns();$('music-run').value=result.id;await loadMusicRun();
  toast('Analysis saved.');
});
$('refresh-music').onclick=()=>run('Refreshing…',async()=>{
  state.project.musical_runs=(await api(`/api/projects/${currentId()}`)).musical_runs;renderMusicRuns();
});
