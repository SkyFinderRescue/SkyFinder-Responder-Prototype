const FIREBASE_VERSION='12.17.1';
const APP_URL=`https://www.gstatic.com/firebasejs/${FIREBASE_VERSION}/firebase-app.js`;
const AUTH_URL=`https://www.gstatic.com/firebasejs/${FIREBASE_VERSION}/firebase-auth.js`;
const DB_URL=`https://www.gstatic.com/firebasejs/${FIREBASE_VERSION}/firebase-database.js`;

export async function connectFirebaseBackend(config,roomId='general'){
  const [{initializeApp},{getAuth,signInAnonymously},{getDatabase,ref,onValue,update,set,onDisconnect,serverTimestamp}]=await Promise.all([
    import(APP_URL),import(AUTH_URL),import(DB_URL)
  ]);

  const app=initializeApp(config);
  const auth=getAuth(app);
  const credential=await signInAnonymously(auth);
  const uid=credential.user.uid;
  const db=getDatabase(app);
  const responderRef=ref(db,`rooms/${roomId}/responders/${uid}`);
  const connectedRef=ref(db,'.info/connected');
  let callsign='Responder';
  let sessionId=crypto.randomUUID?.()||`${Date.now()}-${Math.random()}`;
  let connUnsub=null;

  function armDisconnect(){
    const disconnector=onDisconnect(responderRef);
    disconnector.update({online:false,last_seen_ms:serverTimestamp()}).catch(()=>{});
  }
  connUnsub=onValue(connectedRef,snap=>{if(snap.val()===true)armDisconnect();});

  return{
    name:'Firebase RTDB',
    currentUserId:uid,
    async setProfile(profile){callsign=profile.callsign||callsign;},
    async publishPosition(point){
      await update(responderRef,{
        callsign,
        lat:point.lat,
        lng:point.lng,
        ce_m:point.accuracy_m??null,
        hae_m:point.altitude_m??null,
        le_m:point.altitude_accuracy_m??null,
        heading_deg:point.heading_deg??null,
        speed_mps:point.speed_mps??null,
        device_time_ms:point.device_time_ms,
        server_time_ms:serverTimestamp(),
        online:true,
        freshness_ttl_ms:60000,
        session_id:sessionId
      });
    },
    async appendTrack(point,slot){
      await set(ref(db,`rooms/${roomId}/tracks/${uid}/${slot}`),{
        lat:point.lat,lng:point.lng,
        device_time_ms:point.device_time_ms,
        server_time_ms:serverTimestamp()
      });
    },
    subscribeResponders(callback){return onValue(ref(db,`rooms/${roomId}/responders`),snap=>callback(snap.val()||{}));},
    subscribeTracks(callback){return onValue(ref(db,`rooms/${roomId}/tracks`),snap=>callback(snap.val()||{}));},
    async setSharingState(online){
      await update(responderRef,{callsign,online:Boolean(online),last_seen_ms:serverTimestamp(),server_time_ms:serverTimestamp()});
    },
    async stop(){
      try{await update(responderRef,{online:false,last_seen_ms:serverTimestamp(),server_time_ms:serverTimestamp()});}catch{}
      try{connUnsub?.();}catch{}
    }
  };
}
