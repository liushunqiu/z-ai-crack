const fs=require('fs'),vm=require('vm');
process.on('unhandledRejection', e=>console.error('unhandled',e&&e.stack||e));
const aliyun=fs.readFileSync('zaibot/artifacts/captcha/AliyunCaptcha.js','utf8');
let code=fs.readFileSync('zaibot/artifacts/captcha/feilin058.full.js','utf8');
const runtimeInitPath=process.env.FEILIN_INIT_JSON||'';
let runtimeInit={};
if(runtimeInitPath) runtimeInit=JSON.parse(fs.readFileSync(runtimeInitPath,'utf8'));
function parseDcPlain(plain){ const p=String(plain||'').split('#'); return {secretKey:Buffer.from(p[0]||'','base64').toString('utf8'), flag:Buffer.from(p[1]||'','base64').toString('utf8'), sessionId:p[2]||'', version:p[3]||'', timestamp:p[7]||'', ip:p[8]||''}; }
let runtimeDc={};
if(process.env.FEILIN_DC_PLAIN) runtimeDc=parseDcPlain(process.env.FEILIN_DC_PLAIN);
const RUNTIME={deviceConfig:runtimeInit.DeviceConfig||process.env.FEILIN_DEVICE_CONFIG||'', certifyId:runtimeInit.CertifyId||'', secretKey:process.env.FEILIN_SECRET_KEY||runtimeDc.secretKey||'4c899e75cd24d1a5', sessionId:process.env.FEILIN_SESSION_ID||runtimeDc.sessionId||'3795d28242a11619bc25f786f84e53d4-h-1779980547659-623166930bf34f86b275cb617b2f5195', timestamp:Number(process.env.FEILIN_TIMESTAMP||runtimeDc.timestamp||1779980547660), ip:process.env.FEILIN_IP||runtimeDc.ip||'134.195.101.90', version:process.env.FEILIN_VERSION||runtimeDc.version||'1.4.2/feilin058.4a6794d7892b46b11f077bbd7dbe49e7f983b847e94ec3a0c9fce8362072dd96'};

code=code.replace("e.d(r,{jz:function(){return x},oj:function(){return N}});", "e.d(r,{jz:function(){return x},oj:function(){return N}});try{window.__m5375=r}catch(_){};");
code=code.replace("function N(t){try{return btoa(t)}catch(r){return btoa(unescape(encodeURIComponent(t)))}}", "function N(t){try{const s=String(t);if(s.includes('WEB')||s.includes('SG_'))console.log('[PATCH api-btoa-N]',t);if(s==='#####null'){const fixed=window.__RUNTIME.sessionId+'#'+window.__RUNTIME.secretKey+'#'+window.__RUNTIME.ip+'#'+window.__RUNTIME.timestamp+'#desktop';console.log('[PATCH btoa-null-fix]',fixed.slice(0,100));return btoa(fixed);}return btoa(t)}catch(r){return btoa(unescape(encodeURIComponent(t)))}}");
code=code.replace("(d^=106,q=tn[tK])", "(d^=106,q=window.__PREID_FLAG?'SG_WEB_PREID':tn[tK])");
code=code.replace("uN[lD.call(7,26,374)](-8)", "(console.log('[PATCH uN.slice vars]', {uN:uN, rp:rp, ik:typeof ik===\'undefined\'?\'U\':ik, ix:typeof ix===\'undefined\'?\'U\':ix, iU:typeof iU===\'undefined\'?\'U\':iU, u8:typeof u8===\'undefined\'?\'U\':u8, key:lD.call(7,26,374)}), (uN||'')[lD.call(7,26,374)](-8))");
code=code.replace("M=(0,c.getCookieUid)(),r=11", "M=(0,c.getCookieUid)(),console.log('[PATCH M cookieUid]', M),r=11");
code=code.replace("S=(0,c.getLocalStorage)()", "S=(0,c.getLocalStorage)(),console.log('[PATCH S localStorage]', S)");
code=code.replace("N=(0,c.getLocalStorageUid)()", "N=(0,c.getLocalStorageUid)(),console.log('[PATCH N localStorageUid]', N)");
code=code.replace("uN=(0,c.jz)(e$,st)", "uN=(0,c.oj)(e$,st),window.__last_st=st,window.__last_uN=uN,console.log('[PATCH uN forced oj]',{uN:uN,e$:e$,st:st})");
code=code.replace("st=o.vc[(lD(),lD)(67,478)]", "st=window.__RUNTIME.sessionId||o.vc[(lD(),lD)(67,478)],console.log('[PATCH st assign]',{st:st, key:(lD(),lD)(67,478), vcKeys:Object.keys(o.vc||{}).slice(0,80)})");
code=code.replace("t7={secretKey:(0,h.oj)(j,K),sessionId:(0,h.oj)(t6,B)}", "t7={secretKey:window.__RUNTIME.secretKey,sessionId:window.__RUNTIME.sessionId},console.log('[PATCH t7 forced]',t7,{j:j,K:K,t6:t6,B:B})");
code=code.replace("tC=[q,tR,tJ,t$,G]", "tC=[q,(q==='SG_WEB'||q==='SG_WEB_PREID')&&(!tR)?(typeof st!=='undefined'?st:window.__last_st):tR,(q==='SG_WEB'||q==='SG_WEB_PREID')&&(!tJ)?(window.__last_payload_from_tm||(typeof uN!=='undefined'?uN:window.__last_uN)):tJ,t$,window.__last_payload_from_tm?require('crypto').createHash('md5').update(window.__last_payload_from_tm).digest('hex'):G],console.log('[PATCH token array]',{q:q,tR:tR,tJ:tJ,st:typeof st==='undefined'?'U':st,uN:typeof uN==='undefined'?'U':uN,tC:tC})");
code=code.replace('return v}var s=[u][0](49,45)+u', "if(tN===501&&tm&&String(tm).includes('#')){window.__last_tm=tm; try{window.__last_payload_from_tm=(0,o.oj)(window.__RUNTIME.secretKey,tm)}catch(_){}} console.log('[PATCH f return]',{v:v,q:q,tR:tR,tJ:tJ,t$:t$,G:G,S:S,t3:t3,tC:tC,tQ:tQ,tN:tN,tm:tm,tP:tP,tz:tz,k:k,to:to,x:x,lastPayload:window.__last_payload_from_tm,R:R&&Object.keys(R).slice?Object.keys(R).slice(0,20):R});return v}var s=[u][0](49,45)+u");
function Storage(){}; Storage.prototype={getItem(k){return this[k]||null},setItem(k,v){console.log('[storage.set]',k,String(v).slice(0,160));this[k]=String(v)},removeItem(k){delete this[k]}};
function Elem(tag='div'){this.tagName=tag.toUpperCase();this.style={setProperty(){}};this.children=[];this.clientWidth=300;this.clientHeight=150;this.width=300;this.height=150;this.classList={add(){},remove(){},contains(){return false}};this.attributes=[];this.sheet=null;this.contentWindow=null;this.contentDocument=null;}
function makeStyleSheets(){ const sheet={cssRules:[{cssText:'body{}', selectorText:'body', style:{cssText:'', length:0, item(){return ''}, getPropertyValue(){return ''}}}], rules:null, ownerNode:null, href:null, media:{mediaText:'all', length:1, item(){return 'all'}}, disabled:false}; sheet.rules=sheet.cssRules; return [sheet]; }
Elem.prototype.appendChild=function(x){this.children.push(x); if(x.onload) setTimeout(x.onload,0); return x};
Elem.prototype.setAttribute=function(k,v){this[k]=v; this.attributes.push({name:k,value:v})}; Elem.prototype.getAttribute=function(k){return this[k]||null}; Elem.prototype.getBoundingClientRect=function(){return {x:0,y:0,left:0,top:0,width:this.clientWidth,height:this.clientHeight,right:this.clientWidth,bottom:this.clientHeight}}; Elem.prototype.addEventListener=function(){}; Elem.prototype.removeEventListener=function(){};
function makeCanvas2D(){
  const grad={addColorStop(){}};
  return {canvas:null, fillStyle:'#000', strokeStyle:'#000', font:'10px sans-serif', textBaseline:'alphabetic', textAlign:'start', globalCompositeOperation:'source-over', lineWidth:1,
    fillRect(){}, clearRect(){}, strokeRect(){}, rect(){}, beginPath(){}, closePath(){}, moveTo(){}, lineTo(){}, bezierCurveTo(){}, quadraticCurveTo(){}, arc(){}, arcTo(){}, fill(){}, stroke(){}, clip(){},
    fillText(){}, strokeText(){}, measureText(t){return {width:String(t).length*7, actualBoundingBoxLeft:0, actualBoundingBoxRight:String(t).length*7};},
    createLinearGradient(){return grad}, createRadialGradient(){return grad}, createPattern(){return {};},
    getImageData(x=0,y=0,w=10,h=10){const d=new Uint8ClampedArray(Math.max(1,w*h*4));for(let i=0;i<d.length;i++)d[i]=Math.floor(Math.random()*256);return {width:w,height:h,data:d};}, putImageData(){}, drawImage(){},
    save(){}, restore(){}, translate(){}, rotate(){}, scale(){}, transform(){}, setTransform(){}, resetTransform(){},
    isPointInPath(){return false}, isPointInStroke(){return false}
  };
}
function makeWebGL(){return {getExtension(n){return n==='WEBGL_debug_renderer_info'?{UNMASKED_VENDOR_WEBGL:37445,UNMASKED_RENDERER_WEBGL:37446}:null},getParameter(p){ if(p===37445) return 'Intel Inc.'; if(p===37446) return 'Intel Iris OpenGL Engine'; return 1},getSupportedExtensions(){return ['WEBGL_debug_renderer_info']},clearColor(){},clear(){},createBuffer(){return {}},bindBuffer(){},bufferData(){},createProgram(){return {}},createShader(){return {}},shaderSource(){},compileShader(){},attachShader(){},linkProgram(){},useProgram(){},getAttribLocation(){return 0},getUniformLocation(){return {}},enableVertexAttribArray(){},vertexAttribPointer(){},uniform2f(){},drawArrays(){},readPixels(x,y,w,h,fmt,type,pixels){ if(pixels&&pixels.length) for(let i=0;i<pixels.length;i++) pixels[i]=i%251;}}}
Elem.prototype.getContext=function(type){ const t=String(type||'').toLowerCase(); if(t==='2d'){const c=makeCanvas2D(); c.canvas=this; return c;} return makeWebGL();};
const document={defaultView:null,documentElement:Object.assign(new Elem('html'),{clientWidth:1920,clientHeight:1080, style:{MozAppearance:undefined,setProperty(){}}}),head:new Elem('head'),body:Object.assign(new Elem('body'),{clientWidth:1920,clientHeight:1080}),cookie:'',createElement:(t)=>{const e=new Elem(t); const tag=String(t).toLowerCase(); if(tag==='canvas'){e.toDataURL=()=> 'data:image/png;base64,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';} if(tag==='iframe'){const idoc={...document}; const iw={...window, document:idoc}; idoc.defaultView=iw; e.contentWindow=iw; e.contentDocument=idoc;} if(tag==='style'||tag==='link'){e.sheet=makeStyleSheets()[0];} return e;},createTextNode:t=>({textContent:t}),getElementsByTagName:()=>[new Elem()],getElementById:()=>null,querySelector:(sel)=> sel==='canvas'? (()=>{const e=new Elem('canvas'); e.toDataURL=()=> 'data:image/png;base64,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'; return e})():null,querySelectorAll:()=>[],styleSheets:makeStyleSheets(),fonts:{check(){return true}, ready:Promise.resolve()},addEventListener(){},removeEventListener(){}};
const navigator={userAgent:'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36', appVersion:'5.0 (Macintosh; Intel Mac OS X 10_15_7)', appName:'Netscape', vendor:'Google Inc.', platform:'MacIntel', language:'en-US', languages:['en-US','en'], hardwareConcurrency:8, deviceMemory:8, maxTouchPoints:0, cookieEnabled:true, webdriver:false, plugins:[1,2,3], mimeTypes:[1,2], userAgentData:{brands:[{brand:'Chromium',version:'148'},{brand:'Google Chrome',version:'148'},{brand:'Not=A?Brand',version:'99'}], mobile:false, platform:'macOS', getHighEntropyValues(keys){return Promise.resolve({brands:this.brands, mobile:false, platform:'macOS', architecture:'x86', bitness:'64', model:'', platformVersion:'10.15.7', uaFullVersion:'148.0.0.0', fullVersionList:this.brands});}}, webkitTemporaryStorage:{queryUsageAndQuota(ok){ok(0,1073741824*10)}}};
const screen={width:1920,height:1080,colorDepth:24,pixelDepth:24,availWidth:1920,availHeight:1055};
const window={__RUNTIME:RUNTIME,chrome:{runtime:{}, loadTimes(){return {}}, csi(){return {}}}, document,navigator,screen,innerWidth:1920,innerHeight:1080,outerWidth:1920,outerHeight:1080,devicePixelRatio:2,location:{href:'https://chat.z.ai/',protocol:'https:',host:'chat.z.ai',hostname:'chat.z.ai',pathname:'/'},localStorage:new Storage(),sessionStorage:new Storage(),performance:{now:()=>Date.now(),memory:{jsHeapSizeLimit:4294705152}},crypto:{getRandomValues(a){return require('crypto').webcrypto.getRandomValues(a)}},addEventListener(){},removeEventListener(){},dispatchEvent(){},matchMedia(q){return {matches:false,media:q,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}},getComputedStyle(){return {fontSize:'10px',lineHeight:'10px',cssText:'', length:0, item(){return ''}, getPropertyValue(){return ''}}},setTimeout,clearTimeout,setInterval,clearInterval,atob:s=>Buffer.from(s,'base64').toString('binary'),btoa:s=>Buffer.from(s,'binary').toString('base64'),openDatabase(){},webkitRequestFileSystem(t,s,ok){ok&&ok({})}};
Object.assign(window,{Storage,Window:function(){},Element:Elem,HTMLElement:Elem,NodeList:Array,HTMLCollection:Array,CustomEvent:function(){},Event:function(){},Image:function(){},Audio:function(){},Blob:function(){},File:function(){},FileReader:function(){},URL,Location:window.Location,Text:window.Text,WebGLRenderingContext:function(){}});
window.Location=function(){}; document.defaultView=window; window.window=window; window.self=window; window.top=window; window.parent=window; window.globalThis=window;
class XMLHttpRequest {
  open(method,url,async=true){this.method=method;this.url=url;this.async=async;this.headers={};this.status=200;this.statusText='OK';this.responseType='text';}
  setRequestHeader(k,v){this.headers[k]=v;}
  send(body){this.body=body;
    // Log2 detected - pass through original Data
    if(String(body||'').includes('Action=Log2')){
      console.log('[XHR] Log2 detected');
    }
    console.log('[XHR]', this.method, this.url, String(body||'').slice(0,200));
    const _doFetch = (url, opts) => {
      const https = require('https');
      const http = require('http');
      const parsed = new URL(url);
      const mod = parsed.protocol === 'https:' ? https : http;
      return new Promise((resolve, reject) => {
        const req = mod.request({hostname:parsed.hostname,port:parsed.port,path:parsed.pathname+parsed.search,method:opts.method||'POST',headers:opts.headers||{}}, (res) => {
          let data = '';
          res.on('data', c => data += c);
          res.on('end', () => resolve({status:res.statusCode, statusText:res.statusMessage, text:async()=>data}));
        });
        req.on('error', reject);
        if(opts.body) req.write(opts.body);
        req.end();
      });
    };
    _doFetch(this.url, {method:this.method||'POST', headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8', ...(this.headers||{})}, body})
      .then(async r=>{ const txt=await r.text(); this.status=r.status; this.statusText=r.statusText; this.response=txt; console.log('[XHR.response]', r.status, 'len='+txt.length, txt.slice(0,300)); try{window.__lastXhrResponse=JSON.parse(txt)}catch(_){}; window.__lastXhrUrl=this.url; this.onload&&this.onload(); })
      .catch(e=>{ console.log('[XHR.error]', e && (e.stack||e.message)); this.status=0; this.statusText='ERR'; this.onerror&&this.onerror(e); });
  }
}
window.__PREID_STUB='SG_WEB_PREID#3795d28242a11619bc25f786f84e53d4-h-'+Date.now()+'-00000000000000000000000000000000#STUBPAYLOAD#0#e1a2045a96f8b07b7fdc47673fd4700d'; 
function Worker(url){ this.url=url; this.onmessage=null; this.onerror=null; }
Worker.prototype.postMessage=function(msg){ console.log('[Worker.post]', this.url, JSON.stringify(msg).slice(0,200)); setTimeout(()=>{ this.onmessage&&this.onmessage({data:{}}); },0); };
Worker.prototype.terminate=function(){};
window.Worker=Worker;
window.XMLHttpRequest=XMLHttpRequest;
const _realFetch=globalThis.fetch; // Save real Node.js fetch
window.fetch=async (url,opts={})=>{console.log('[fetch]', url, opts&&String(opts.body||'').slice(0,200));
  const https=require('https'),http=require('http');const parsed=new URL(url);const mod=parsed.protocol==='https:'?https:http;
  return new Promise((resolve,reject)=>{const req=mod.request({hostname:parsed.hostname,port:parsed.port,path:parsed.pathname+parsed.search,method:opts.method||'GET',headers:opts.headers||{}},res=>{let data='';res.on('data',c=>data+=c);res.on('end',()=>{try{window.__lastFetchResponse=JSON.parse(data)}catch(_){};window.__lastFetchUrl=url;resolve({ok:res.statusCode>=200&&res.statusCode<300,status:res.statusCode,text:async()=>data,json:async()=>JSON.parse(data)})});});req.on('error',reject);if(opts.body)req.write(opts.body);req.end();});};

window.Math=Object.create(Math); window.Math.random=()=>Math.random();const ctx={window,document,navigator,screen,Location:function(){},location:window.location,localStorage:window.localStorage,sessionStorage:window.sessionStorage,performance:window.performance,crypto:window.crypto,Math:window.Math,require,console,setTimeout,clearTimeout,setInterval,clearInterval,atob:window.atob,btoa:window.btoa,Storage,Element:Elem,HTMLElement:Elem,NodeList:Array,HTMLCollection:Array,CustomEvent:window.CustomEvent,Event:window.Event,Image:window.Image,Audio:window.Audio,Blob:window.Blob,File:window.File,FileReader:window.FileReader,URL,Worker,XMLHttpRequest,fetch:window.fetch,WebGLRenderingContext:window.WebGLRenderingContext,moveTo(){},moveBy(){},scrollTo(){},open(){},close(){},resizeTo(){},resizeBy(){},confirm(){return false},print(){},Option:function(){},Screen:function(){},Attr:function(){},Range:function(){},Text:function(){},CSSRule:function(){},CSSStyleRule:function(){},matchMedia:window.matchMedia.bind(window),scrollBy(){},moveBy(){},resizeTo(){},resizeBy(){},alert(){}};
ctx.self=window; ctx.globalThis=ctx;
vm.createContext(ctx);
vm.runInContext(aliyun,ctx,{timeout:5000});
vm.runInContext(code,ctx,{timeout:5000});
console.log('FEILIN keys',Object.keys(window.FEILIN));
let done=false;
window.um={}; window.z_um={};
const INIT_DEVICE_CONFIG=(RUNTIME.deviceConfig||'NNL1bHlNo1b2ms1KfBly3y33BiC1RRyqIswU+Fl6QvdrjZDjTiyXJQQd3KnmaFvXMxyhSuSykfiCzNyviwORhYe1FP4igjIVxzBKw+D1e9dN0rT/zPdZaGxKjqXpAywDge4wTHYf4D4XYOJMw8kAWGfSg/z3aJv0AEH4+HG/fwSbRLwbRCQcF2+clSZJt9Ra4t0vRun0UgAskB1Rd4GX/XWHEXTau3uWYkaGMLxmWdIWKpEyoQtn7AdNX2wi7BzIWjCRFFZejKBVez1fVVmcya1s1O6rK/expyHDK11D732TiNJ7mepAc/5Jp6URYEPC');
const cfg={SceneId:'didk33e0', sceneId:'didk33e0', appName:'saf-captcha', appKey:'3795d28242a11619bc25f786f84e53d4', endpoints:['https://ap-southeast-1.device.saf.aliyuncs.com/'], dev:false, version:'1.4.2', timestamp:RUNTIME.timestamp, sessionId:RUNTIME.sessionId, secretKey:RUNTIME.secretKey, deviceData:'1', deviceConfig:INIT_DEVICE_CONFIG, deviceToken:'', DeviceToken:'', APP_KEY:'3795d28242a11619bc25f786f84e53d4', APP_NAME:'saf-captcha', APP_VERSION:'1.4.2', PLATFORM:'W', ENDPOINTS:['https://ap-southeast-1.device.saf.aliyuncs.com/'], ACCESS_SEC:'45f8ac1e1de14397', KEY_ID:process.env.DEVICE_KEY_ID||'YOUR_DEVICE_KEY_ID', KEY_SECRET:process.env.DEVICE_KEY_SECRET||'YOUR_DEVICE_KEY_SECRET', API_VERSION:'2020-10-15', WEB_AES_FLAG_SECRET_KEY:'45f8ac1e1de14397', DEVICE_TYPE:{WEB:'W'}, key:RUNTIME.secretKey, switch:1, pluginElements:'', pluginResource:'', globalVariable:'', ip:RUNTIME.ip, DeviceConfig:INIT_DEVICE_CONFIG, WEB_REGION:{CN:'WEB',SG:'SG_WEB'}, WEB_REGION_PREID:{CN:'WEB_PREID',SG:'SG_WEB_PREID'}};
window.__PREID_FLAG=!!process.env.FEILIN_USE_PREID;
if(process.env.FEILIN_FULL_FLOW!=='1'){
  window.FEILIN.initFeiLin(cfg,(status,res)=>{console.log('callback',status,res); done=true;});
}
// If FEILIN_CERTIFY_ID is set, also init with it (to trigger SG_WEB_PREID path)
if(process.env.FEILIN_CERTIFY_ID){
  const cfg2={...cfg, certifyId:process.env.FEILIN_CERTIFY_ID, CertifyId:process.env.FEILIN_CERTIFY_ID};
  window.FEILIN.initFeiLin(cfg2,(status,res)=>{console.log('callback2',status,res);});
}
if(process.env.FEILIN_FULL_FLOW!=='1'){
  setTimeout(()=>{
    console.log('=== TOKEN EXTRACTION ===');
    let sgWebToken=null;
    try{ sgWebToken=window.um.getToken('abc'); }catch(e){ console.error('getToken("abc") err',e.message); }
    if(sgWebToken){
      const decoded=Buffer.from(sgWebToken,'base64').toString();
      console.log('[SG_WEB_TOKEN]', decoded.split('#')[0], decoded.slice(0,80));
    }
    if(sgWebToken){
      fs.writeFileSync(__dirname+'/zaibot_sg_web_token.txt', sgWebToken);
    }
    console.log('callback done=', done);
    if(!done) console.log('not done');
  },5000);
}

// Full flow mode: FEILIN_FULL_FLOW=1
if(process.env.FEILIN_FULL_FLOW==='1'){
  setTimeout(async()=>{
    const crypto=require('crypto');
    console.log('=== FULL FLOW MODE ===');
    // Step 1: InitCaptchaV3 via captcha_protocol.js
    console.log('--- Step 1: InitCaptchaV3 ---');
    const {execSync}=require('child_process');
    const initJson=execSync('node '+__dirname+'/captcha_protocol.js init',{encoding:'utf8',timeout:30000});
    const init=JSON.parse(initJson);
    console.log('CertifyId:', init.CertifyId);
    if(!init.CertifyId){console.error('InitCaptchaV3 failed');process.exit(1);}
    // Parse new DeviceConfig
    const C=window.__ALIYUN_CRYPT;
    const dcPlain=C.AES.decrypt(String(init.DeviceConfig),C.enc.Utf8.parse('87f879f135f27da7'),{iv:C.enc.Utf8.parse('0123456789ABCDEF'),padding:C.pad.Pkcs7}).toString(C.enc.Utf8);
    const parts=dcPlain.split('#');
    const newSK=Buffer.from(parts[0]||'','base64').toString('utf8');
    const newSID=parts[2]||'';
    console.log('New sessionId:', newSID.slice(0,60));
    console.log('New secretKey:', newSK);
    // Step 2: initFeiLin with CertifyId + new DeviceConfig
    console.log('--- Step 2: initFeiLin with CertifyId ---');
    window.__PREID_FLAG=true;
    // Update __RUNTIME so FeiLin reads new values
    window.__RUNTIME.secretKey=newSK;
    window.__RUNTIME.sessionId=newSID;
    window.__RUNTIME.timestamp=Number(parts[7]||Date.now());
    window.__RUNTIME.ip=parts[8]||'134.195.101.90';
    window.__RUNTIME.deviceConfig=init.DeviceConfig;
    window.__RUNTIME.DeviceConfig=init.DeviceConfig;
    window.__RUNTIME.certifyId=init.CertifyId;
    window.__RUNTIME.CertifyId=init.CertifyId;
    const newCfg={...cfg,
      deviceConfig:init.DeviceConfig, DeviceConfig:init.DeviceConfig,
      sessionId:newSID, secretKey:newSK,
      timestamp:window.__RUNTIME.timestamp, ip:window.__RUNTIME.ip,
      certifyId:init.CertifyId, CertifyId:init.CertifyId
    };
    let preidToken=null;
    window.FEILIN.initFeiLin(newCfg,(status,res)=>{
      console.log('initFeiLin callback:', status);
      if(res&&res.DeviceToken){
        preidToken=res.DeviceToken;
        console.log('[CALLBACK] DeviceToken captured, len:', preidToken.length);
      } else {
        console.log('[CALLBACK] No DeviceToken in response:', JSON.stringify(res).slice(0,100));
      }
    });
    // Wait for initFeiLin to complete
    await new Promise(r=>setTimeout(r,8000));
    // Try getToken() first (might have better payload)
    let getTokenResult=null;
    try{ getTokenResult=window.um.getToken(); }catch(e){ console.log('[getToken] err:',e.message); }
    if(getTokenResult){
      const dec=Buffer.from(getTokenResult,'base64').toString();
      console.log('[getToken] prefix:', dec.split('#')[0]);
      console.log('[getToken] sessionId:', dec.split('#')[1]?.slice(0,60));
      console.log('[getToken] payload len:', dec.split('#')[2]?.length);
    }
    // Use getToken result if available, otherwise callback token
    if(getTokenResult) preidToken=getTokenResult;
    if(!preidToken){ console.error('No DeviceToken'); process.exit(1); }
    const decoded=Buffer.from(preidToken,'base64').toString();
    console.log('Token prefix:', decoded.split('#')[0]);
    console.log('Token sessionId:', decoded.split('#')[1]?.slice(0,60));
    fs.writeFileSync(__dirname+'/zaibot_preid_token.txt', preidToken);
    // Step 3: VerifyCaptchaV3
    console.log('--- Step 3: VerifyCaptchaV3 ---');
    function signOpenApi(params,secret){const p={...params};delete p.Signature;const canonical=Object.keys(p).sort().map(k=>encodeURIComponent(k)+'='+encodeURIComponent(p[k])).join('&');const stringToSign='POST&'+encodeURIComponent('/')+'&'+encodeURIComponent(canonical);return crypto.createHmac('sha1',secret+'&').update(stringToSign).digest('base64');}
    function formBody(params){return Object.keys(params).map(k=>encodeURIComponent(k)+'='+encodeURIComponent(params[k])).join('&');}
    const cvp=JSON.stringify({sceneId:'didk33e0',certifyId:init.CertifyId,deviceToken:preidToken});
    console.log('[CVP] certifyId:', init.CertifyId);
    console.log('[CVP] deviceToken prefix:', Buffer.from(preidToken,'base64').toString().split('#')[0]);
    console.log('[CVP] deviceToken sessionId:', Buffer.from(preidToken,'base64').toString().split('#')[1]?.slice(0,60));
    const p2={AccessKeyId:process.env.CAPTCHA_KEY_ID||'YOUR_CAPTCHA_KEY_ID',SignatureMethod:'HMAC-SHA1',SignatureVersion:'1.0',Format:'JSON',Timestamp:new Date().toISOString().replace(/\.\d{3}Z$/,'Z'),Version:'2023-03-05',Action:'VerifyCaptchaV3',SceneId:'didk33e0',CertifyId:init.CertifyId,CaptchaVerifyParam:cvp,SignatureNonce:crypto.randomUUID()};
    p2.Signature=signOpenApi(p2,process.env.CAPTCHA_KEY_SECRET||'YOUR_CAPTCHA_KEY_SECRET');
    const body=formBody(p2);
    const verifyUrl='https://no8xfe.captcha-open-southeast.aliyuncs.com/';
    const https=require('https');
    const url=new URL(verifyUrl);
    const options={hostname:url.hostname,port:443,path:url.pathname,method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','Content-Length':Buffer.byteLength(body)}};
    const text=await new Promise((resolve,reject)=>{
      const req=https.request(options,(res)=>{
        let data='';
        res.on('data',chunk=>data+=chunk);
        res.on('end',()=>resolve(data));
      });
      req.on('error',reject);
      req.write(body);
      req.end();
    });
    let verify;try{verify=JSON.parse(text);}catch{verify={raw:text};}
    console.log('VerifyCaptchaV3:', JSON.stringify(verify,null,2));
    if(verify.Result&&verify.Result.securityToken){
      console.log('=== SUCCESS ===');
      const param=Buffer.from(JSON.stringify({certifyId,sceneId:'didk33e0',isSign:true,securityToken:verify.Result.securityToken})).toString('base64');
      fs.writeFileSync(__dirname+'/zaibot_captcha_cache.json',JSON.stringify({captcha_verify_param:param,ts:Math.floor(Date.now()/1000),source:'feilin_vm_probe_full_flow'},null,2));
      console.log('captcha_verify_param:', param.slice(0,80)+'...');
    } else { console.log('VerifyCaptchaV3 failed:', verify.Result&&verify.Result.VerifyCode); }
  },8000);
}

// Also test: call InitCaptchaV3 externally, then check getToken again
if(process.env.FEILIN_FULL_FLOW!=='1'){
  setTimeout(async()=>{
    console.log('=== POST-INIT TOKEN TEST ===');
    try{
      const res=await fetch('https://no8xfe.captcha-open-southeast.aliyuncs.com/',{
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},
        body:'Action=InitCaptchaV3&SceneId=didk33e0&Language=en&Mode=popup'
      });
      const data=await res.json();
      console.log('[InitCaptchaV3] CertifyId:', data.CertifyId);
      let postInitToken=null;
      try{ postInitToken=window.um.getToken(); }catch(e){ console.error('post-init getToken() err',e.message); }
      if(postInitToken){
        const decoded=Buffer.from(postInitToken,'base64').toString();
        const prefix=decoded.split('#')[0];
        console.log('[POST_INIT_TOKEN] prefix='+prefix, decoded.slice(0,100));
      }
    }catch(e){ console.error('[InitCaptchaV3 err]', e.message); }
  },10000);
}

// TRACELESS mode: FEILIN_TRACELESS=1
// New flow: InitCaptchaV3 → FeiLin generate deviceToken → VerifyCaptchaV3
// No Log1/Log2 needed! CaptchaType: TRACELESS
if(process.env.FEILIN_TRACELESS==='1'){
  setTimeout(async()=>{
    const crypto=require('crypto');
    const https=require('https');
    console.log('=== TRACELESS FLOW MODE ===');
    console.log('No Log1/Log2 needed - using TRACELESS captcha flow');

    // Helper functions
    function signOpenApi(params,secret){
      const p={...params}; delete p.Signature;
      const canonical=Object.keys(p).sort().map(k=>encodeURIComponent(k)+'='+encodeURIComponent(p[k])).join('&');
      const stringToSign='POST&'+encodeURIComponent('/')+'&'+encodeURIComponent(canonical);
      return crypto.createHmac('sha1',secret+'&').update(stringToSign).digest('base64');
    }
    function formBody(params){
      return Object.keys(params).map(k=>encodeURIComponent(k)+'='+encodeURIComponent(params[k])).join('&');
    }
    function postForm(url,params){
      const body=formBody(params);
      return new Promise((resolve,reject)=>{
        const urlObj=new URL(url);
        const req=https.request({
          hostname:urlObj.hostname,port:443,path:urlObj.pathname,method:'POST',
          headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','Content-Length':Buffer.byteLength(body)}
        },(res)=>{
          let data='';res.on('data',c=>data+=c);
          res.on('end',()=>{try{resolve(JSON.parse(data))}catch{resolve({raw:data})}});
        });
        req.on('error',reject);req.write(body);req.end();
      });
    }

    // Step 1: InitCaptchaV3 with DeviceData
    console.log('--- Step 1: InitCaptchaV3 ---');
    // Generate DeviceData using AES encryption (same as captcha_protocol.js)
    function aesEncrypt(plain,key){
      const cipher=crypto.createCipheriv('aes-128-cbc',Buffer.from(key,'utf8'),Buffer.from('0123456789ABCDEF','utf8'));
      cipher.setAutoPadding(true);
      return Buffer.concat([cipher.update(plain,'utf8'),cipher.final()]).toString('base64');
    }
    const innerDeviceData=`W#saf-captcha#didk33e0#captcha-normal#no8xfe#sgp`;
    const flagDeviceData=aesEncrypt(innerDeviceData,'45f8ac1e1de14397');
    const deviceData=aesEncrypt(`3795d28242a11619bc25f786f84e53d4#W#${flagDeviceData}#1.4.2#CLOUD#`,'45f8ac1e1de14397');

    const initParams={
      AccessKeyId:process.env.CAPTCHA_KEY_ID||'YOUR_CAPTCHA_KEY_ID',
      SignatureMethod:'HMAC-SHA1',SignatureVersion:'1.0',Format:'JSON',
      Timestamp:new Date().toISOString().replace(/\.\d{3}Z$/,'Z'),
      Version:'2023-03-05',Action:'InitCaptchaV3',SceneId:'didk33e0',
      Language:'en',Mode:'popup',UpLang:'true',DeviceData:deviceData,
      SignatureNonce:crypto.randomUUID()
    };
    initParams.Signature=signOpenApi(initParams,process.env.CAPTCHA_KEY_SECRET||'YOUR_CAPTCHA_KEY_SECRET');
    const init=await postForm('https://no8xfe.captcha-open-southeast.aliyuncs.com/',initParams);
    console.log('InitCaptchaV3 result:', JSON.stringify(init));
    if(!init.CertifyId){console.error('InitCaptchaV3 failed');process.exit(1);}
    console.log('CertifyId:', init.CertifyId);
    console.log('CaptchaType:', init.CaptchaType);
    console.log('DeviceConfig:', init.DeviceConfig?.slice(0,60)+'...');

    // Parse DeviceConfig to get sessionId, secretKey, etc.
    const C=window.__ALIYUN_CRYPT;
    const dcPlain=C.AES.decrypt(String(init.DeviceConfig),C.enc.Utf8.parse('87f879f135f27da7'),{iv:C.enc.Utf8.parse('0123456789ABCDEF'),padding:C.pad.Pkcs7}).toString(C.enc.Utf8);
    const parts=dcPlain.split('#');
    const newSK=Buffer.from(parts[0]||'','base64').toString('utf8');
    const newSID=parts[2]||'';
    const newTimestamp=Number(parts[7]||Date.now());
    const newIP=parts[8]||'134.195.101.90';
    console.log('New sessionId:', newSID.slice(0,60));
    console.log('New secretKey:', newSK);

    // Step 2: initFeiLin with CertifyId + DeviceConfig to generate deviceToken
    console.log('--- Step 2: initFeiLin (TRACELESS) ---');
    // Don't set __PREID_FLAG - browser uses SG_WEB, not SG_WEB_PREID
    window.__PREID_FLAG=false;
    window.__RUNTIME.secretKey=newSK;
    window.__RUNTIME.sessionId=newSID;
    window.__RUNTIME.timestamp=newTimestamp;
    window.__RUNTIME.ip=newIP;
    window.__RUNTIME.deviceConfig=init.DeviceConfig;
    window.__RUNTIME.DeviceConfig=init.DeviceConfig;
    window.__RUNTIME.certifyId=init.CertifyId;
    window.__RUNTIME.CertifyId=init.CertifyId;

    const cfg2={
      SceneId:'didk33e0',sceneId:'didk33e0',appName:'saf-captcha',
      appKey:'3795d28242a11619bc25f786f84e53d4',
      endpoints:['https://ap-southeast-1.device.saf.aliyuncs.com/'],
      dev:false,version:'1.4.2',timestamp:newTimestamp,
      sessionId:newSID,secretKey:newSK,deviceData:'1',
      deviceConfig:init.DeviceConfig,deviceToken:'',DeviceToken:'',
      APP_KEY:'3795d28242a11619bc25f786f84e53d4',APP_NAME:'saf-captcha',
      APP_VERSION:'1.4.2',PLATFORM:'W',
      ENDPOINTS:['https://ap-southeast-1.device.saf.aliyuncs.com/'],
      ACCESS_SEC:'45f8ac1e1de14397',KEY_ID:process.env.DEVICE_KEY_ID||'YOUR_DEVICE_KEY_ID',
      KEY_SECRET:process.env.DEVICE_KEY_SECRET||'YOUR_DEVICE_KEY_SECRET',API_VERSION:'2020-10-15',
      WEB_AES_FLAG_SECRET_KEY:'45f8ac1e1de14397',DEVICE_TYPE:{WEB:'W'},
      key:newSK,switch:1,pluginElements:'',pluginResource:'',
      globalVariable:'',ip:newIP,DeviceConfig:init.DeviceConfig,
      WEB_REGION:{CN:'WEB',SG:'SG_WEB'},
      WEB_REGION_PREID:{CN:'WEB_PREID',SG:'SG_WEB_PREID'},
      certifyId:init.CertifyId,CertifyId:init.CertifyId
    };

    let deviceToken=null;
    window.FEILIN.initFeiLin(cfg2,(status,res)=>{
      console.log('initFeiLin callback:', status);
      if(res&&res.DeviceToken){
        deviceToken=res.DeviceToken;
        console.log('[CALLBACK] DeviceToken captured, len:', deviceToken.length);
      } else {
        console.log('[CALLBACK] No DeviceToken:', JSON.stringify(res).slice(0,100));
      }
    });

    // Wait for FeiLin to complete
    await new Promise(r=>setTimeout(r,8000));

    // Try getToken()
    try{
      const token=window.um.getToken();
      if(token){
        deviceToken=token;
        const decoded=Buffer.from(token,'base64').toString();
        console.log('[getToken] prefix:', decoded.split('#')[0]);
        console.log('[getToken] sessionId:', decoded.split('#')[1]?.slice(0,60));
      }
    }catch(e){console.log('[getToken] err:',e.message);}

    if(!deviceToken){console.error('No DeviceToken generated');process.exit(1);}
    fs.writeFileSync(__dirname+'/zaibot_preid_token.txt',deviceToken);

    // Decode and show token info
    const decoded=Buffer.from(deviceToken,'base64').toString();
    console.log('Token prefix:', decoded.split('#')[0]);
    console.log('Token sessionId:', decoded.split('#')[1]?.slice(0,60));

    // Step 3: VerifyCaptchaV3
    console.log('--- Step 3: VerifyCaptchaV3 ---');
    const cvp=JSON.stringify({sceneId:'didk33e0',certifyId:init.CertifyId,deviceToken});
    const verifyParams={
      AccessKeyId:process.env.CAPTCHA_KEY_ID||'YOUR_CAPTCHA_KEY_ID',
      SignatureMethod:'HMAC-SHA1',SignatureVersion:'1.0',Format:'JSON',
      Timestamp:new Date().toISOString().replace(/\.\d{3}Z$/,'Z'),
      Version:'2023-03-05',Action:'VerifyCaptchaV3',SceneId:'didk33e0',
      CertifyId:init.CertifyId,CaptchaVerifyParam:cvp,
      SignatureNonce:crypto.randomUUID()
    };
    verifyParams.Signature=signOpenApi(verifyParams,process.env.CAPTCHA_KEY_SECRET||'YOUR_CAPTCHA_KEY_SECRET');
    const verify=await postForm('https://no8xfe.captcha-open-southeast.aliyuncs.com/',verifyParams);
    console.log('VerifyCaptchaV3:', JSON.stringify(verify,null,2));

    if(verify.Result&&verify.Result.securityToken){
      console.log('=== SUCCESS ===');
      const param=Buffer.from(JSON.stringify({
        certifyId:init.CertifyId,sceneId:'didk33e0',
        isSign:true,securityToken:verify.Result.securityToken
      })).toString('base64');
      fs.writeFileSync(__dirname+'/zaibot_captcha_cache.json',JSON.stringify({
        captcha_verify_param:param,ts:Math.floor(Date.now()/1000),
        source:'feilin_vm_probe_traceless'
      },null,2));
      console.log('captcha_verify_param:', param.slice(0,80)+'...');
    } else {
      console.log('VerifyCaptchaV3 failed:', verify.Result?.VerifyCode);
    }
  },8000);
}
