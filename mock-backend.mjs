export function connectMockBackend(){
  const uid='local-test-user';
  const responders={
    'mock-2':{callsign:'Rescue 2',lat:34.4252,lng:-119.7142,ce_m:6,online:true,server_time_ms:Date.now()},
    'mock-3':{callsign:'Rescue 3',lat:34.4176,lng:-119.6995,ce_m:9,online:true,server_time_ms:Date.now()}
  };
  const tracks={};
  const responderSubs=new Set(),trackSubs=new Set();
  let callsign='Test Responder';
  let timer=null;
  const emitResponders=()=>responderSubs.forEach(cb=>cb(structuredClone(responders)));
  const emitTracks=()=>trackSubs.forEach(cb=>cb(structuredClone(tracks)));

  function startSimulation(){
    if(timer)return;
    timer=setInterval(()=>{
      const now=Date.now();
      for(const [id,r] of Object.entries(responders)){
        if(id===uid)continue;
        r.lat+=((Math.random()-.5)*0.00018);
        r.lng+=((Math.random()-.5)*0.00018);
        r.server_time_ms=now;r.online=true;
        tracks[id]??={};
        tracks[id][String(Math.floor(now/15000)%120)]={lat:r.lat,lng:r.lng,server_time_ms:now,device_time_ms:now};
      }
      emitResponders();emitTracks();
    },5000);
  }
  startSimulation();

  return{
    name:'Mock / isolated',
    currentUserId:uid,
    async setProfile(profile){callsign=profile.callsign||callsign;},
    async publishPosition(point){
      responders[uid]={callsign,lat:point.lat,lng:point.lng,ce_m:point.accuracy_m??null,heading_deg:point.heading_deg??null,speed_mps:point.speed_mps??null,device_time_ms:point.device_time_ms,server_time_ms:Date.now(),online:true,freshness_ttl_ms:60000,session_id:'mock-session'};
      emitResponders();
    },
    async appendTrack(point,slot){
      tracks[uid]??={};
      tracks[uid][String(slot)]={lat:point.lat,lng:point.lng,device_time_ms:point.device_time_ms,server_time_ms:Date.now()};
      emitTracks();
    },
    subscribeResponders(callback){responderSubs.add(callback);callback(structuredClone(responders));return()=>responderSubs.delete(callback);},
    subscribeTracks(callback){trackSubs.add(callback);callback(structuredClone(tracks));return()=>trackSubs.delete(callback);},
    async setSharingState(online){
      responders[uid]??={callsign,lat:34.4208,lng:-119.6982,ce_m:null};
      responders[uid].online=Boolean(online);responders[uid].server_time_ms=Date.now();emitResponders();
    },
    async stop(){if(responders[uid]){responders[uid].online=false;responders[uid].server_time_ms=Date.now();emitResponders();}}
  };
}
