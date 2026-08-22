import{freshnessState,formatAge,formatDistanceImperial,sanitizeCallsign,shouldPublishPosition,shouldPublishTrack,TRACK_RING_SIZE}from'./core.mjs';
import{connectMockBackend}from'./mock-backend.mjs';

const $=id=>document.getElementById(id);
const callsignEl=$('callsign'),startBtn=$('startBtn'),stopBtn=$('stopBtn'),messageEl=$('message'),modeBadge=$('modeBadge'),backendNameEl=$('backendName'),myStatusEl=$('myStatus'),gpsAgeEl=$('gpsAge'),gpsAccuracyEl=$('gpsAccuracy'),rosterEl=$('roster'),responderCountEl=$('responderCount');
const map=L.map('map',{zoomControl:true}).setView([34.4208,-119.6982],13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);

const markerById=new Map(),trackById=new Map();
let backend=null,watchId=null,sharing=false,lastPublished=null,lastPublishedMs=0,lastTrack=null,lastTrackMs=0,lastGpsMs=0,lastAccuracyM=null,trackSeq=Number(localStorage.getItem('responderTrackSeq')||0),latestResponders={};
let centeredOnMe=false;

callsignEl.value=localStorage.getItem('responderCallsign')||'';

function setMessage(text,error=false){messageEl.textContent=text;messageEl.style.color=error?'#a12622':'#485467';}
function markerIcon(state,callsign){return L.divIcon({className:'',html:`<div class="marker-shell"><div class="responder-dot ${state}"></div><div class="marker-label">${escapeHtml(callsign)}</div></div>`,iconSize:[110,28],iconAnchor:[11,14]});}
function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

async function initBackend(){
  try{
    const cfg=await import('./firebase-config.js');
    if(!cfg.firebaseConfig)throw new Error('firebaseConfig export missing');
    const mod=await import('./firebase-backend.mjs');
    backend=await mod.connectFirebaseBackend(cfg.firebaseConfig,'general');
    modeBadge.textContent='FIREBASE TEST';
    backendNameEl.textContent='Firebase RTDB';
    setMessage('Firebase test backend connected. This remains isolated from production SkyFinder.');
  }catch(error){
    backend=connectMockBackend();
    modeBadge.textContent='MOCK MODE';
    backendNameEl.textContent='Mock / isolated';
    setMessage(`Firebase connection failed, so the prototype is in mock mode: ${error.message}`,true);
  }
  backend.subscribeResponders(renderResponders);
  backend.subscribeTracks(renderTracks);
}

function renderResponders(data){
  latestResponders=data||{};
  const now=Date.now();
  const rows=[];
  for(const[id,r]of Object.entries(latestResponders)){
    if(!Number.isFinite(Number(r.lat))||!Number.isFinite(Number(r.lng)))continue;
    const seen=Number(r.server_time_ms||r.last_seen_ms||0);
    const state=freshnessState(now,seen,r.online!==false);
    const callsign=r.callsign||'Responder';
    let marker=markerById.get(id);
    if(!marker){marker=L.marker([r.lat,r.lng],{icon:markerIcon(state.key,callsign)}).addTo(map);markerById.set(id,marker);}else{marker.setLatLng([r.lat,r.lng]);marker.setIcon(markerIcon(state.key,callsign));}
    marker.bindPopup(`<strong>${escapeHtml(callsign)}</strong><br>${state.label} — ${formatAge(state.ageMs)} old<br>Accuracy: ${r.ce_m?Math.round(r.ce_m*3.28084)+' ft':'—'}`);
    let distance='—';
    const me=latestResponders[backend?.currentUserId];
    if(me&&id!==backend?.currentUserId){const meters=distanceMeters(Number(me.lat),Number(me.lng),Number(r.lat),Number(r.lng));distance=formatDistanceImperial(meters);}
    rows.push({id,callsign,state,distance,accuracy:r.ce_m?`${Math.round(r.ce_m*3.28084)} ft`:'—'});
  }
  for(const[id,marker]of markerById){if(!latestResponders[id]){map.removeLayer(marker);markerById.delete(id);}}
  rows.sort((a,b)=>a.callsign.localeCompare(b.callsign));
  responderCountEl.textContent=String(rows.length);
  rosterEl.innerHTML=rows.map(row=>`<div class="responder-row"><strong>${escapeHtml(row.callsign)}</strong><span class="state ${row.state.key}">${row.state.label}</span><span class="secondary">${formatAge(row.state.ageMs)} old</span><span class="secondary">${row.id===backend?.currentUserId?'YOU':row.distance}</span></div>`).join('')||'<div>No responder positions yet.</div>';
  const mine=backend?.currentUserId?latestResponders[backend.currentUserId]:null;
  if(mine){
    const state=freshnessState(now,Number(mine.server_time_ms||mine.last_seen_ms||0),mine.online!==false);
    myStatusEl.textContent=sharing?state.label:'OFFLINE';
    if(sharing&&!centeredOnMe){map.setView([Number(mine.lat),Number(mine.lng)],16);centeredOnMe=true;}
  }
}

function renderTracks(allTracks){
  const currentIds=new Set();
  for(const[uid,slots]of Object.entries(allTracks||{})){
    const points=Object.values(slots||{}).filter(p=>Number.isFinite(Number(p.lat))&&Number.isFinite(Number(p.lng))).sort((a,b)=>Number(a.server_time_ms||a.device_time_ms||0)-Number(b.server_time_ms||b.device_time_ms||0));
    if(points.length<2)continue;
    currentIds.add(uid);
    const latlngs=points.map(p=>[Number(p.lat),Number(p.lng)]);
    let line=trackById.get(uid);
    if(!line){line=L.polyline(latlngs,{weight:3,opacity:.55,dashArray:'5 6'}).addTo(map);trackById.set(uid,line);}else line.setLatLngs(latlngs);
  }
  for(const[id,line]of trackById){if(!currentIds.has(id)){map.removeLayer(line);trackById.delete(id);}}
}

function distanceMeters(lat1,lng1,lat2,lng2){const r=6371000,toRad=d=>d*Math.PI/180,dLat=toRad(lat2-lat1),dLng=toRad(lng2-lng1),a=Math.sin(dLat/2)**2+Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLng/2)**2;return 2*r*Math.asin(Math.sqrt(a));}

async function startSharing(){
  const callsign=sanitizeCallsign(callsignEl.value);
  if(!callsign){setMessage('Enter a call sign before going live.',true);return;}
  if(!navigator.geolocation){setMessage('This browser does not provide geolocation.',true);return;}
  localStorage.setItem('responderCallsign',callsign);callsignEl.value=callsign;
  await backend.setProfile({callsign});
  sharing=true;centeredOnMe=false;startBtn.disabled=true;stopBtn.disabled=false;callsignEl.disabled=true;myStatusEl.textContent='STARTING';
  setMessage('Requesting high-accuracy GPS. If prompted, allow location access.');
  watchId=navigator.geolocation.watchPosition(handlePosition,handleGpsError,{enableHighAccuracy:true,maximumAge:3000,timeout:20000});
}

async function handlePosition(pos){
  if(!sharing)return;
  const c=pos.coords,now=Date.now();
  const point={lat:Number(c.latitude),lng:Number(c.longitude),accuracy_m:Number.isFinite(c.accuracy)?Number(c.accuracy):null,altitude_m:Number.isFinite(c.altitude)?Number(c.altitude):null,altitude_accuracy_m:Number.isFinite(c.altitudeAccuracy)?Number(c.altitudeAccuracy):null,heading_deg:Number.isFinite(c.heading)?Number(c.heading):null,speed_mps:Number.isFinite(c.speed)?Number(c.speed):null,device_time_ms:Number(pos.timestamp||now)};
  lastGpsMs=now;lastAccuracyM=point.accuracy_m;gpsAgeEl.textContent='0s';gpsAccuracyEl.textContent=lastAccuracyM?`${Math.round(lastAccuracyM*3.28084)} ft`:'—';
  try{
    if(shouldPublishPosition(lastPublished,point,now,lastPublishedMs)){await backend.publishPosition(point);lastPublished=point;lastPublishedMs=now;}
    if(shouldPublishTrack(lastTrack,point,now,lastTrackMs)){trackSeq=(trackSeq+1)%1000000;localStorage.setItem('responderTrackSeq',String(trackSeq));await backend.appendTrack(point,trackSeq%TRACK_RING_SIZE);lastTrack=point;lastTrackMs=now;}
    myStatusEl.textContent='LIVE';
  }catch(error){setMessage(`Location obtained, but backend update failed: ${error.message}`,true);myStatusEl.textContent='DELAYED';}
}

function handleGpsError(error){const msg={1:'Location permission was denied.',2:'GPS position is currently unavailable.',3:'GPS request timed out.'}[error.code]||error.message||'GPS error';setMessage(msg,true);myStatusEl.textContent='DELAYED';}

async function stopSharing(){
  sharing=false;if(watchId!==null){navigator.geolocation.clearWatch(watchId);watchId=null;}
  try{await backend.setSharingState(false);}catch{}
  startBtn.disabled=false;stopBtn.disabled=true;callsignEl.disabled=false;myStatusEl.textContent='OFFLINE';setMessage('Location sharing stopped. Your last point remains visibly aged/stale for test purposes.');
}

startBtn.addEventListener('click',startSharing);stopBtn.addEventListener('click',stopSharing);
window.addEventListener('pagehide',()=>{if(sharing)backend?.setSharingState(false).catch(()=>{});});
setInterval(()=>{const now=Date.now();if(lastGpsMs)gpsAgeEl.textContent=formatAge(now-lastGpsMs);renderResponders(latestResponders);},1000);

await initBackend();
