const fs=require('fs');
const crypto=require('crypto');
function hmac(key,msg){return crypto.createHmac('sha256', key).update(msg).digest('hex')}
function hmacBytes(key,msg){return crypto.createHmac('sha256', key).update(msg).digest()}
globalThis.iS={sha256:{hmac:(key,msg)=>({toString:()=>hmac(key,msg)})}};
globalThis.TextEncoder = require('util').TextEncoder;
globalThis.btoa = s => Buffer.from(s,'binary').toString('base64');
let code=fs.readFileSync('zaibot/artifacts/analysis/sign_chunk.js','utf8');
code += `\nconsole.log('decode', {encode: wl(404,'Ls52'), length: wl(393,'Kz[%'), slice: wl(395,'mscT'), fromCharCode: wl(392,'t69k'), from: wl(428,'I%Jk'), floor: wl(402,'Vt1e'), sha256a: wl(370,'!)k&'), hmac1: wl(375,'TPo7'), secret: wl(394,'Kz[%'), sha256b: wl(423,'b2x$'), hmac2: wl(425,'NXX0')});\n`;
code += `\nlet t='requestId:6bd3f462-9a05-4781-8cbc-756d8223b959,timestamp:1779956218691,user_id:f9274699-c59d-486c-979c-215fbd9dcb36'; let e='hello'; let r='1779956218691'; console.log(nV(t,e,r));`;
eval(code);
