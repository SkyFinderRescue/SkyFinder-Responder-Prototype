export const LIVE_MAX_MS=15000;
export const DELAYED_MAX_MS=60000;
export const MOVING_PUBLISH_MS=5000;
export const STATIONARY_PUBLISH_MS=20000;
export const TRACK_PUBLISH_MS=15000;
export const TRACK_RING_SIZE=120;

export function haversineMeters(a,b){
  if(!a||!b)return Infinity;
  const r=6371000;
  const toRad=d=>d*Math.PI/180;
  const dLat=toRad(b.lat-a.lat),dLng=toRad(b.lng-a.lng);
  const la1=toRad(a.lat),la2=toRad(b.lat);
  const h=Math.sin(dLat/2)**2+Math.cos(la1)*Math.cos(la2)*Math.sin(dLng/2)**2;
  return 2*r*Math.asin(Math.sqrt(h));
}

export function freshnessState(nowMs,lastSeenMs,online=true){
  const age=Math.max(0,Number(nowMs)-Number(lastSeenMs||0));
  if(online&&age<=LIVE_MAX_MS)return{key:'live',label:'LIVE',ageMs:age};
  if(age<=DELAYED_MAX_MS)return{key:'delayed',label:'DELAYED',ageMs:age};
  return{key:'stale',label:'STALE',ageMs:age};
}

export function shouldPublishPosition(previous,next,nowMs,lastPublishMs){
  if(!previous||!lastPublishMs)return true;
  const moved=haversineMeters(previous,next);
  const elapsed=nowMs-lastPublishMs;
  const moving=moved>=5 || Number(next.speed_mps||0)>=0.8;
  return elapsed>=(moving?MOVING_PUBLISH_MS:STATIONARY_PUBLISH_MS);
}

export function shouldPublishTrack(previousTrack,next,nowMs,lastTrackMs){
  if(!previousTrack||!lastTrackMs)return true;
  return nowMs-lastTrackMs>=TRACK_PUBLISH_MS && haversineMeters(previousTrack,next)>=8;
}

export function formatAge(ms){
  if(!Number.isFinite(ms))return '—';
  const s=Math.max(0,Math.round(ms/1000));
  if(s<60)return `${s}s`;
  const m=Math.floor(s/60),rs=s%60;
  if(m<60)return `${m}m ${rs}s`;
  const h=Math.floor(m/60),rm=m%60;
  return `${h}h ${rm}m`;
}

export function formatDistanceImperial(meters){
  if(!Number.isFinite(meters))return '—';
  const feet=meters*3.280839895;
  if(feet<528)return `${Math.round(feet)} ft`;
  return `${(feet/5280).toFixed(2)} mi`;
}

export function sanitizeCallsign(value){
  return String(value||'').replace(/[^A-Za-z0-9 ._\-]/g,'').trim().slice(0,32);
}
