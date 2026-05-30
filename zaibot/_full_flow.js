#!/usr/bin/env node
// Self-contained full flow: InitCaptchaV3 -> SG_WEB_PREID -> VerifyCaptchaV3
// All in one FeiLin VM session
const fs=require('fs'),vm=require('vm'),crypto=require('crypto'),https=require('https');
const BASE=__dirname;
const aliyun=fs.readFileSync(BASE+'/artifacts/captcha/AliyunCaptcha.js','utf8');
let code=fs.readFileSync(BASE+'/artifacts/captcha/feilin058.full.js','utf8');

// Initial DeviceConfig (from a previous InitCaptchaV3 call)
const INIT_DC='NNL1bHlNo1b2ms1KfBly3y33BiC1RRyqIswU+Fl6QvdrjZDjTiyXJQQd3KnmaFvXMxyhSuSykfiCzNyviwORhYe1FP4igjIVxzBKw+D1e9dN0rT/zPdZaGxKjqXpAywDge4wTHYf4D4XYOJMw8kAWGfSg/z3aJv0AEH4+HG/fwSbRLwbRCQcF2+clSZJt9Ra4t0vRun0UgAskB1Rd4GX/XWHEXTau3uWYkaGMLxmWdIWKpEyoQtn7AdNX2wi7BzIWjCRFFZejKBVez1fVVmcya1s1O6rK/expyHDK11D732TiNJ7mepAc/5Jp6URYEPC';
const RUNTIME={secretKey:'4c899e75cd24d1a5',sessionId:'3795d28242a11619bc25f786f84e53d4-h-1779980547659-623166930bf34f86b275cb617b2f5195',timestamp:1779980547660,ip:'134.195.101.90',deviceConfig:INIT_DC};

// Patches
code=code.replace('t7={secretKey:(0,h.oj)(j,K),sessionId:(0,h.oj)(t6,B)}','t7={secretKey:window.__RUNTIME.secretKey,sessionId:window.__RUNTIME.sessionId}');
code=code.replace('uN=(0,c.jz)(e$,st)','uN=(0,c.oj)(e$,st)');
code=code.replace("(d^=106,q=tn[tK])", "(d^=106,q=window.__PREID_FLAG?'SG_WEB_PREID':tn[tK])");
// Fix #####null
code=code.replace("function N(t){try{return btoa(t)}catch(r){return btoa(unescape(encodeURIComponent(t)))}}", "function N(t){try{const s=String(t);if(s==='#####null'){const f=window.__RUNTIME.sessionId+'#'+window.__RUNTIME.secretKey+'#'+window.__RUNTIME.ip+'#'+window.__RUNTIME.timestamp+'#desktop';return btoa(f);}return btoa(t)}catch(r){return btoa(unescape(encodeURIComponent(t)))}}");

// Minimal browser env
function Storage(){};Storage.prototype={getItem(k){return this[k]||null},setItem(k,v){this[k]=String(v)},removeItem(k){delete this[k]}};
function Elem(tag){this.tagName=(tag||'div').toUpperCase();this.style={setProperty(){}};this.children=[];this.clientWidth=300;this.clientHeight=150;}
Elem.prototype.appendChild=function(x){this.children.push(x);if(x.onload)setTimeout(x.onload,0);return x};
Elem.prototype.setAttribute=function(){};Elem.prototype.getAttribute=function(){return null};
Elem.prototype.getBoundingClientRect=function(){return{x:0,y:0,left:0,top:0,width:300,height:150,right:300,bottom:150}};
Elem.prototype.addEventListener=function(){};Elem.prototype.removeEventListener=function(){};
function makeCanvas2D(){return{canvas:null,fillStyle:'#000',strokeStyle:'#000',font:'10px sans-serif',textBaseline:'alphabetic',fillRect(){},clearRect(){},beginPath(){},closePath(){},moveTo(){},lineTo(){},arc(){},fill(){},stroke(){},fillText(){},strokeText(){},measureText(t){return{width:String(t).length*7}},getImageData(x,y,w,h){return{width:w,height:h,data:new Uint8ClampedArray(w*h*4).map((_,i)=>i%251)}},save(){},restore(){}};}
function makeWebGL(){return{getExtension(n){return n==='WEBGL_debug_renderer_info'?{UNMASKED_VENDOR_WEBGL:37445,UNMASKED_RENDERER_WEBGL:37446}:null},getParameter(p){if(p===37445)return'Intel Inc.';if(p===37446)return'Intel Iris OpenGL Engine';return 1},getSupportedExtensions(){return['WEBGL_debug_renderer_info']},readPixels(x,y,w,h,fmt,type,pixels){if(pixels&&pixels.length)for(let i=0;i<pixels.length;i++)pixels[i]=i%251}}};
Elem.prototype.getContext=function(type){if(String(type).toLowerCase()==='2d'){const c=makeCanvas2D();c.canvas=this;return c;}return makeWebGL();};
const document={defaultView:null,documentElement:Object.assign(new Elem('html'),{clientWidth:1920,clientHeight:1080,style:{MozAppearance:undefined,setProperty(){}}}),head:new Elem('head'),body:Object.assign(new Elem('body'),{clientWidth:1920,clientHeight:1080}),cookie:'',createElement:(t)=>{const e=new Elem(t);if(t==='canvas')e.toDataURL=()=>'data:image/png;base64,AAA';if(t==='iframe'){const idoc={...document};const iw={...window,document:idoc};idoc.defaultView=iw;e.contentWindow=iw;e.contentDocument=idoc;}return e;},createTextNode:t=>({textContent:t}),getElementsByTagName:()=>[new Elem()],getElementById:()=>null,querySelector:()=>null,querySelectorAll:()=>[],styleSheets:[{cssRules:[{cssText:'body{}',selectorText:'body',style:{cssText:'',length:0,item(){return''},getPropertyValue(){return''}}}],rules:null}],fonts:{check(){return true},ready:Promise.resolve()},addEventListener(){},removeEventListener(){}};
const navigator={userAgent:'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',appVersion:'5.0 (Macintosh; Intel Mac OS X 10_15_7)',appName:'Netscape',vendor:'Google Inc.',platform:'MacIntel',language:'en-US',languages:['en-US','en'],hardwareConcurrency:8,deviceMemory:8,maxTouchPoints:0,cookieEnabled:true,webdriver:false,plugins:[1,2,3],mimeTypes:[1,2],userAgentData:{brands:[{brand:'Chromium',version:'148'},{brand:'Google Chrome',version:'148'},{brand:'Not=A?Brand',version:'99'}],mobile:false,platform:'macOS',getHighEntropyValues(keys){return Promise.resolve({brands:this.brands,mobile:false,platform:'macOS',architecture:'x86',bitness:'64',model:'',platformVersion:'10.15.7',uaFullVersion:'148.0.0.0',fullVersionList:this.brands})}},webkitTemporaryStorage:{queryUsageAndQuota(ok){ok(0,1073741824*10)}}};
const screen={width:1920,height:1080,colorDepth:24,pixelDepth:24,availWidth:1920,availHeight:1055};
const window={__RUNTIME:RUNTIME,chrome:{runtime:{},loadTimes(){return{}},csi(){return{}}},document,navigator,screen,innerWidth:1920,innerHeight:1080,outerWidth:1920,outerHeight:1080,devicePixelRatio:2,location:{href:'https://chat.z.ai/',protocol:'https:',host:'chat.z.ai',hostname:'chat.z.ai',pathname:'/'},localStorage:new Storage(),sessionStorage:new Storage(),performance:{now:()=>Date.now(),memory:{jsHeapSizeLimit:4294705152}},crypto:{getRandomValues(a){return require('crypto').webcrypto.getRandomValues(a)}},addEventListener(){},removeEventListener(){},dispatchEvent(){},matchMedia(q){return{matches:false,media:q,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){}}},getComputedStyle(){return{fontSize:'10px',lineHeight:'10px',cssText:'',length:0,item(){return''},getPropertyValue(){return''}}},setTimeout,clearTimeout,setInterval,clearInterval,atob:s=>Buffer.from(s,'base64').toString('binary'),btoa:s=>Buffer.from(s,'binary').toString('base64'),openDatabase(){}};
Object.assign(window,{Storage,Window:function(){},Element:Elem,HTMLElement:Elem,NodeList:Array,HTMLCollection:Array,CustomEvent:function(){},Event:function(){},Image:function(){},Audio:function(){},Blob:function(){},File:function(){},FileReader:function(){},URL,Location:function(){},Text:function(){},WebGLRenderingContext:function(){}});
document.defaultView=window;window.window=window;window.self=window;window.top=window;window.parent=window;window.globalThis=window;

// Real XHR that tracks responses
let log2Response=null;
class XMLHttpRequest{open(m,u,a){this.method=m;this.url=u;this.async=a;this.headers={};}setRequestHeader(k,v){this.headers[k]=v;}send(body){this.body=body;
  globalThis.fetch(this.url,{method:this.method||'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',...(this.headers||{})},body})
    .then(async r=>{const txt=await r.text();this.status=r.status;this.statusText=r.statusText;this.response=txt;if(this.url.includes('Log2')){log2Response={status:r.status,body:txt};console.log('[Log2]',r.status,txt.slice(0,200));}this.onload&&this.onload();})
    .catch(e=>{this.status=0;this.statusText='ERR';this.onerror&&this.onerror(e);});
}}
function Worker(url){this.url=url;this.onmessage=null;this.onerror=null;}
Worker.prototype.postMessage=function(msg){setTimeout(()=>{this.onmessage&&this.onmessage({data:{}});},0);};
Worker.prototype.terminate=function(){};
window.Worker=Worker;window.XMLHttpRequest=XMLHttpRequest;window.fetch=async(url,opts={})=>{console.log('[fetch]',url);return{ok:true,status:200,text:async()=>JSON.stringify({Code:'Success',Success:true,Result:{}}),json:async()=>({Code:'Success',Success:true,Result:{}})};};
window.Math=Object.create(Math);window.Math.random=()=>0.123456789;
const ctx={window,document,navigator,screen,Location:function(){},location:window.location,localStorage:window.localStorage,sessionStorage:window.sessionStorage,performance:window.performance,crypto:window.crypto,Math:window.Math,require,console,setTimeout,clearTimeout,setInterval,clearInterval,atob:window.atob,btoa:window.btoa,Storage,Element:Elem,HTMLElement:Elem,NodeList:Array,HTMLCollection:Array,CustomEvent:window.CustomEvent,Event:window.Event,Image:window.Image,Audio:window.Audio,Blob:window.Blob,File:window.File,FileReader:window.FileReader,URL,Worker,XMLHttpRequest,fetch:window.fetch,WebGLRenderingContext:window.WebGLRenderingContext,moveTo(){},moveBy(){},scrollTo(){},open(){},close(){},resizeTo(){},resizeBy(){},confirm(){return false},print(){},Option:function(){},Screen:function(){},Attr:function(){},Range:function(){},Text:window.Text,CSSRule:function(){},CSSStyleRule:function(){},matchMedia:window.matchMedia.bind(window),scrollBy(){},alert(){}};
ctx.self=window;ctx.globalThis=ctx;
vm.createContext(ctx);
vm.runInContext(aliyun,ctx,{timeout:5000});
vm.runInContext(code,ctx,{timeout:5000});
window.um={};window.z_um={};
const initCfg={SceneId:'didk33e0',sceneId:'didk33e0',appName:'saf-captcha',appKey:'3795d28242a11619bc25f786f84e53d4',endpoints:['https://ap-southeast-1.device.saf.aliyuncs.com/'],dev:false,version:'1.4.2',timestamp:RUNTIME.timestamp,sessionId:RUNTIME.sessionId,secretKey:RUNTIME.secretKey,deviceData:'1',deviceConfig:RUNTIME.deviceConfig,deviceToken:'',DeviceToken:'',APP_KEY:'3795d28242a11619bc25f786f84e53d4',APP_NAME:'saf-captcha',APP_VERSION:'1.4.2',PLATFORM:'W',ENDPOINTS:['https://ap-southeast-1.device.saf.aliyuncs.com/'],ACCESS_SEC:'45f8ac1e1de14397',KEY_ID:process.env.DEVICE_KEY_ID||'YOUR_DEVICE_KEY_ID',KEY_SECRET:process.env.DEVICE_KEY_SECRET||'YOUR_DEVICE_KEY_SECRET',API_VERSION:'2020-10-15',WEB_AES_FLAG_SECRET_KEY:'45f8ac1e1de14397',DEVICE_TYPE:{WEB:'W'},key:RUNTIME.secretKey,switch:1,pluginElements:'',pluginResource:'',globalVariable:'',ip:RUNTIME.ip,DeviceConfig:RUNTIME.deviceConfig,WEB_REGION:{CN:'WEB',SG:'SG_WEB'},WEB_REGION_PREID:{CN:'WEB_PREID',SG:'SG_WEB_PREID'}};
let feilinReady=false;
window.FEILIN.initFeiLin(initCfg,(status,res)=>{console.log('[initFeiLin]',status);feilinReady=true;});

// OpenAPI signing helpers
const CFG={captchaKeyId:process.env.CAPTCHA_KEY_ID||'YOUR_CAPTCHA_KEY_ID',captchaKeySecret:process.env.CAPTCHA_KEY_SECRET||'YOUR_CAPTCHA_KEY_SECRET',deviceKeyId:process.env.DEVICE_KEY_ID||'YOUR_DEVICE_KEY_ID',deviceKeySecret:process.env.DEVICE_KEY_SECRET||'YOUR_DEVICE_KEY_SECRET',sceneId:'didk33e0',region:'sgp',prefix:'no8xfe',appKey:'3795d28242a11619bc25f786f84e53d4',appName:'saf-captcha',platform:'W',appVersion:'1.4.2',reqAesKey:'45f8ac1e1de14397',resAesKey:'87f879f135f27da7',iv:'0123456789ABCDEF'};
function percentEncode(s){return encodeURIComponent(String(s)).replace(/\+/g,'%20').replace(/\*/g,'%2A').replace(/%7E/g,'~');}
function signOpenApi(params,secret){const p={...params};delete p.Signature;const canonical=Object.keys(p).sort().map(k=>`${percentEncode(k)}=${percentEncode(p[k])}`).join('&');const stringToSign=`POST&${percentEncode('/')}&${percentEncode(canonical)}`;return crypto.createHmac('sha1',secret+'&').update(stringToSign).digest('base64');}
function formBody(params){return Object.keys(params).map(k=>`${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join('&');}
async function postForm(url,params){const body=formBody(params);const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},body});const text=await res.text();let json;try{json=JSON.parse(text);}catch{json={raw:text};}return json;}
function captchaHost(){return CFG.region==='ga'?'https://no8xfe.captcha-open-ga-web.aliyuncs.com/':'https://no8xfe.captcha-open-southeast.aliyuncs.com/';}
async function initCaptcha(){const p={AccessKeyId:CFG.captchaKeyId,SignatureMethod:'HMAC-SHA1',SignatureVersion:'1.0',Format:'JSON',Timestamp:new Date().toISOString().replace(/\.\d{3}Z$/,'Z'),Version:'2023-03-05',Action:'InitCaptchaV3',SceneId:CFG.sceneId,Language:'en',Mode:'popup',DeviceData:'dummy',SignatureNonce:crypto.randomUUID()};p.Signature=signOpenApi(p,CFG.captchaKeySecret);return postForm(captchaHost(),p);}
async function verifyCaptcha(certifyId,deviceToken){const cvp=JSON.stringify({sceneId:CFG.sceneId,certifyId,deviceToken});const p={AccessKeyId:CFG.captchaKeyId,SignatureMethod:'HMAC-SHA1',SignatureVersion:'1.0',Format:'JSON',Timestamp:new Date().toISOString().replace(/\.\d{3}Z$/,'Z'),Version:'2023-03-05',Action:'VerifyCaptchaV3',SceneId:CFG.sceneId,CertifyId:certifyId,CaptchaVerifyParam:cvp,SignatureNonce:crypto.randomUUID()};p.Signature=signOpenApi(p,CFG.captchaKeySecret);return postForm(captchaHost(),p);}

async function main(){
  console.log('=== Step 1: InitCaptchaV3 (via captcha_protocol.js) ===');
  // Use captcha_protocol.js which has proper DeviceData encryption
  const {execSync}=require('child_process');
  const initJson=execSync('node '+BASE+'/captcha_protocol.js init',{encoding:'utf8',timeout:30000});
  const init=JSON.parse(initJson);
  console.log('InitCaptchaV3:', init.Code, init.CertifyId||'no CertifyId');
  if(!init.CertifyId){console.error('InitCaptchaV3 failed');process.exit(1);}

  // Parse new DeviceConfig
  const C=ctx.window.__ALIYUN_CRYPT;
  const dcPlain=C.AES.decrypt(String(init.DeviceConfig),C.enc.Utf8.parse(CFG.resAesKey),{iv:C.enc.Utf8.parse(CFG.iv),padding:C.pad.Pkcs7}).toString(C.enc.Utf8);
  const parts=dcPlain.split('#');
  const newSecretKey=Buffer.from(parts[0]||'','base64').toString('utf8');
  const newSessionId=parts[2]||'';
  const newTimestamp=parts[7]||'';
  const newIp=parts[8]||'';
  console.log('New sessionId:', newSessionId.slice(0,50));
  console.log('New secretKey:', newSecretKey);

  // Update runtime with new DeviceConfig
  window.__RUNTIME.secretKey=newSecretKey;
  window.__RUNTIME.sessionId=newSessionId;
  window.__RUNTIME.timestamp=Number(newTimestamp);
  window.__RUNTIME.ip=newIp;

  console.log('\n=== Step 2: Generate SG_WEB_PREID ===');
  // Wait for FeiLin to be ready
  while(!feilinReady){await new Promise(r=>setTimeout(r,100));}
  window.__PREID_FLAG=true;
  const preidToken=window.um.getToken();
  const preidDecoded=Buffer.from(preidToken,'base64').toString();
  console.log('PREID token prefix:', preidDecoded.split('#')[0]);
  console.log('PREID token len:', preidToken.length);

  console.log('\n=== Step 3: VerifyCaptchaV3 ===');
  const verify=await verifyCaptcha(init.CertifyId, preidToken);
  console.log('VerifyCaptchaV3:', JSON.stringify(verify,null,2));

  if(verify.Result&&verify.Result.securityToken){
    console.log('\n=== SUCCESS ===');
    const param=Buffer.from(JSON.stringify({certifyId:init.CertifyId,sceneId:CFG.sceneId,isSign:true,securityToken:verify.Result.securityToken})).toString('base64');
    console.log('captcha_verify_param:', param.slice(0,80)+'...');
    fs.writeFileSync(BASE+'/zaibot_captcha_cache.json',JSON.stringify({captcha_verify_param:param,ts:Math.floor(Date.now()/1000),source:'_full_flow.js'},null,2));
  }
}
main().catch(e=>{console.error(e);process.exit(1);});
