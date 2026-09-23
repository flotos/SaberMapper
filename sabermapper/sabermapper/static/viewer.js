'use strict';
// SaberMapper viewer: ArcViewer in the middle, the map's explanation on the left, the song top to bottom on the right.
// ArcViewer (a Unity build served from this origin) keeps its song clock on its window: while it plays, the song
// time is soundStartTime + (SongCtx.currentTime - lastPlayed) * playbackSpeed. Jumping reloads it at a new `t`.
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clock = seconds => `${Math.floor(Math.max(0, seconds) / 60)}:${String(Math.floor(Math.max(0, seconds) % 60)).padStart(2, '0')}`;
const params = new URLSearchParams(location.search);
const view = {outline: null, time: Number(params.get('t')) || 0, playing: false, current: null, heard: false};
const THEME_COLORS = ['#e7bb73', '#62c8ed', '#f77a92', '#b9f18d', '#c9a2f2', '#7fd6c2'];

function arcviewerUrl(seconds) {
  return '/arcviewer/?' + new URLSearchParams({url: params.get('map') || '', noProxy: 'true', t: String(Math.max(0, seconds)),
                                               mode: 'Standard', difficulty: params.get('difficulty') || ''});
}

function jump(seconds) {
  view.time = seconds; view.heard = false; view.playing = false;
  $('arcviewer').src = arcviewerUrl(seconds);
  const next = new URL(location.href); next.searchParams.set('t', String(seconds)); history.replaceState(null, '', next);
  render();
}

// ArcViewer's song clock, or null while it has not played since it loaded.
function songTime() {
  try {
    const w = $('arcviewer').contentWindow;
    if (!w || !w.SongCtx || typeof w.soundStartTime !== 'number') return null;
    if (!w.playing) return null;
    return w.soundStartTime + (w.SongCtx.currentTime - w.lastPlayed) * (w.playbackSpeed || 1);
  } catch { return null; }
}

function sectionAt(seconds) {
  const sections = view.outline?.sections || [];
  return sections.find(s => seconds >= s.start_seconds && seconds < s.end_seconds)
    || (seconds < (sections[0]?.start_seconds ?? 0) ? sections[0] : sections[sections.length - 1]);
}

function duration() {
  const o = view.outline; if (!o) return 1;
  return Math.max(o.song.duration_seconds || 0, ...o.sections.map(s => s.end_seconds), 1);
}

function renderRail() {
  const o = view.outline, total = duration(), track = $('rail-track');
  const pct = seconds => `${(100 * seconds / total).toFixed(3)}%`;
  const colors = new Map(o.themes.map((t, i) => [t.id, THEME_COLORS[i % THEME_COLORS.length]]));
  const blocks = o.sections.map(s => `<button class="block" type="button" data-id="${esc(s.id)}" data-at="${s.start_seconds}"
    style="top:${pct(s.start_seconds)};height:${pct(s.end_seconds - s.start_seconds)}" title="${esc(s.summary)}">
    <strong>${esc(s.id)}</strong><span>${clock(s.start_seconds)} · ${esc(s.summary)}</span></button>`).join('');
  const bars = o.themes.flatMap(t => t.spans.map(span => `<div class="theme-bar ${span.role}" title="${esc(t.id)} (${span.role}): ${esc(t.intent || '')}"
    style="top:${pct(span.start_seconds)};height:${pct(span.end_seconds - span.start_seconds)};background:${colors.get(t.id)}"></div>`)).join('');
  track.innerHTML = blocks + bars + '<div id="rail-playhead" class="playhead"></div>';
  track.querySelectorAll('.block').forEach(b => b.onclick = () => jump(Number(b.dataset.at)));
}

function renderStory() {
  const o = view.outline;
  $('song-title').textContent = o.song.title;
  $('song-meta').textContent = `${o.song.artist} · ${o.difficulty} · ${Number(o.song.bpm)} BPM`;
  document.title = `${o.song.title} · SaberMapper viewer`;
  const style = o.style;
  $('style-idea').textContent = style?.idea || 'No style recorded for this map yet.';
  $('style-summary').textContent = style?.summary || 'Ask your assistant to write the map’s summary paragraph.';
  $('style-signatures').innerHTML = (style?.signatures || []).map(s => `<li><strong>${esc(s.theme)}</strong>: ${esc(s.move)}</li>`).join('');
  $('style-more').open = !!style?.summary;
}

function render() {
  const o = view.outline; if (!o) return;
  const section = sectionAt(view.time), total = duration();
  $('now-time').textContent = clock(view.time);
  $('now-state').textContent = view.playing ? '▶ playing' : view.heard ? 'Ⅱ paused' : '';
  const playhead = $('rail-playhead'); if (playhead) playhead.style.top = `${(100 * view.time / total).toFixed(3)}%`;
  if (!section || section === view.current) return;
  view.current = section;
  $('now-name').textContent = section.id;
  $('now-range').textContent = `${clock(section.start_seconds)} – ${clock(section.end_seconds)}`;
  $('now-summary').textContent = section.summary;
  const colors = new Map(o.themes.map((t, i) => [t.id, THEME_COLORS[i % THEME_COLORS.length]]));
  $('now-themes').innerHTML = section.themes.map(t => `<span class="chip" style="color:${colors.get(t)}">${esc(t)}</span>`).join('');
  $('now-evidence-text').textContent = section.evidence || '';
  $('now-evidence').hidden = !section.evidence || section.evidence === section.summary;
  document.querySelectorAll('.block').forEach(b => b.classList.toggle('active', b.dataset.id === section.id));
  const index = o.sections.indexOf(section), next = o.sections[index + 1];
  $('next-button').hidden = !next;
  if (next) { $('next-name').textContent = `${next.id} · ${clock(next.start_seconds)}`; $('next-summary').textContent = next.summary; $('next-button').onclick = () => jump(next.start_seconds); }
}

function tick() {
  const seconds = songTime();
  if (seconds !== null) { view.time = seconds; view.playing = true; view.heard = true; }
  else view.playing = false;  // paused: keep the last time heard (or the start time)
  render();
}

(async () => {
  const project = params.get('project'), difficulty = params.get('difficulty');
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(project)}/outline${difficulty ? `?difficulty=${encodeURIComponent(difficulty)}` : ''}`);
    if (!response.ok) throw new Error(`The map outline could not be read (${response.status})`);
    view.outline = await response.json();
  } catch (error) { $('song-title').textContent = error.message; return; }
  renderStory(); renderRail();
  $('arcviewer').src = arcviewerUrl(view.time);
  render();
  setInterval(tick, 200);
})();
