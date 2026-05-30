#!/usr/bin/env node
/* Protocol/VM Aliyun captcha minting attempt for z.ai.
 * No browser/Playwright dependency. Uses AliyunCaptcha.js only as a local
 * crypto helper to match SDK AES/HMAC behavior, then sends OpenAPI requests.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

const BASE = __dirname;
const SDK_PATH = path.join(BASE, 'artifacts', 'captcha', 'AliyunCaptcha.js');
const CACHE_FILE = path.join(BASE, 'zaibot_captcha_cache.json');

const CFG = {
  sceneId: 'didk33e0',
  prefix: 'no8xfe',
  region: process.env.ZAIBOT_CAPTCHA_REGION || 'sgp',
  language: 'en',
  mode: 'popup',
  verifyType: '3.0',
  appName: 'saf-captcha',
  appKey: '3795d28242a11619bc25f786f84e53d4',
  appVersion: '1.4.2',
  platform: 'W',
  captchaKeyId: process.env.CAPTCHA_KEY_ID || 'YOUR_CAPTCHA_KEY_ID',
  captchaKeySecret: process.env.CAPTCHA_KEY_SECRET || 'YOUR_CAPTCHA_KEY_SECRET',
  deviceKeyId: process.env.DEVICE_KEY_ID || 'YOUR_DEVICE_KEY_ID',
  deviceKeySecret: process.env.DEVICE_KEY_SECRET || 'YOUR_DEVICE_KEY_SECRET',
  // Extracted from AliyunCaptcha.js runtime constants: ve/he/le.
  reqAesKey: '45f8ac1e1de14397',
  resAesKey: '87f879f135f27da7',
  iv: '0123456789ABCDEF',
};

function loadCryptoFromSdk() {
  const code = fs.readFileSync(SDK_PATH, 'utf8');
  const window = {};
  function Elem() { this.style = { setProperty(){} }; this.children = []; }
  Elem.prototype.appendChild = function(x){ this.children.push(x); return x; };
  Elem.prototype.setAttribute = function(){};
  Elem.prototype.addEventListener = function(){};
  const document = {
    documentElement: new Elem(), head: new Elem(), body: new Elem(),
    createElement: () => new Elem(), createTextNode: (t) => ({ textContent: t }),
    getElementsByTagName: () => [new Elem()], getElementById: () => null,
    querySelector: () => null, addEventListener(){}, removeEventListener(){},
  };
  Object.assign(window, {
    document,
    atob: s => Buffer.from(s, 'base64').toString('binary'),
    btoa: s => Buffer.from(s, 'binary').toString('base64'),
    navigator: { userAgent: 'Mozilla/5.0' },
    location: { href: 'https://chat.z.ai/', protocol: 'https:', host: 'chat.z.ai' },
    Element: Elem, CustomEvent: function(){}, Event: function(){},
  });
  const ctx = { window, document, console: {log(){}, warn(){}, error(){}}, setTimeout, clearTimeout, setInterval, clearInterval,
    atob: window.atob, btoa: window.btoa, navigator: window.navigator, location: window.location,
    Element: Elem, CustomEvent: window.CustomEvent, Event: window.Event };
  ctx.globalThis = ctx; ctx.self = window;
  vm.createContext(ctx);
  process.on('unhandledRejection', () => {});
  vm.runInContext(code, ctx, {timeout: 5000});
  if (!window.__ALIYUN_CRYPT) throw new Error('failed to load __ALIYUN_CRYPT');
  return window.__ALIYUN_CRYPT;
}
const C = loadCryptoFromSdk();


function aesDecrypt(cipher, key = CFG.resAesKey) {
  const bytes = C.AES.decrypt(String(cipher), C.enc.Utf8.parse(key), {
    iv: C.enc.Utf8.parse(CFG.iv), padding: C.pad.Pkcs7,
  });
  return bytes.toString(C.enc.Utf8);
}
function parseDeviceConfig(deviceConfig) {
  const plain = aesDecrypt(deviceConfig, CFG.resAesKey);
  const parts = plain.split('#');
  return {plain, secretKey: Buffer.from(parts[0]||'', 'base64').toString('utf8'), flag: Buffer.from(parts[1]||'', 'base64').toString('utf8'), sessionId: parts[2]||'', version: parts[3]||'', pluginElements: parts[4]||'', pluginResource: parts[5]||'', globalVariable: parts[6]||'', timestamp: parts[7]||'', ip: parts[8]||''};
}

function aesEncrypt(plain, key = CFG.reqAesKey) {
  return C.AES.encrypt(String(plain), C.enc.Utf8.parse(key), {
    iv: C.enc.Utf8.parse(CFG.iv), padding: C.pad.Pkcs7,
  }).toString();
}
function deviceData(kind) {
  const inner = `${CFG.platform}#${CFG.appName}#${CFG.sceneId}#${kind}#${CFG.prefix}#${CFG.region}`;
  const flag = aesEncrypt(inner);
  return aesEncrypt([CFG.appKey, CFG.platform, flag, CFG.appVersion, 'CLOUD', ''].join('#'));
}
function percentEncode(s) {
  return encodeURIComponent(String(s)).replace(/\+/g, '%20').replace(/\*/g, '%2A').replace(/%7E/g, '~');
}
function signOpenApi(params, secret) {
  const p = {...params}; delete p.Signature;
  const canonical = Object.keys(p).sort().map(k => `${percentEncode(k)}=${percentEncode(p[k])}`).join('&');
  const stringToSign = `POST&${percentEncode('/')}&${percentEncode(canonical)}`;
  return crypto.createHmac('sha1', secret + '&').update(stringToSign).digest('base64');
}
function uuid() { return crypto.randomUUID(); }
function timestampUTC() { return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'); }
function formBody(params) { return Object.keys(params).map(k => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join('&'); }
async function postForm(url, params) {
  const body = formBody(params);
  const res = await fetch(url, { method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}, body });
  const text = await res.text();
  let json; try { json = JSON.parse(text); } catch { json = {raw: text}; }
  if (!res.ok) throw new Error(`HTTP ${res.status} ${text.slice(0,300)}`);
  return json;
}
function captchaHost() {
  // region=sgp maps to non-ga endpoint. region=ga kept for replay/debug compatibility.
  return CFG.region === 'ga' ? 'https://no8xfe.captcha-open-ga-web.aliyuncs.com/' : 'https://no8xfe.captcha-open-southeast.aliyuncs.com/';
}
function deviceHost() {
  return CFG.region === 'ga' ? 'https://ap-southeast-1-ga.device.saf.aliyuncs.com/' : 'https://ap-southeast-1.device.saf.aliyuncs.com/';
}
async function log1() {
  const p = { AccessKeyId: CFG.deviceKeyId, Version: '2020-10-15', SignatureMethod: 'HMAC-SHA1', SignatureVersion: '1.0', Format: 'JSON', Action: 'Log1', Data: deviceData('captcha-front'), SignatureNonce: uuid() };
  p.Signature = signOpenApi(p, CFG.deviceKeySecret);
  return postForm(deviceHost(), p);
}
function log2Data(sessionId, secretKey, ip, timestamp) {
  const innerPlain = [sessionId, secretKey, ip, timestamp, 'desktop'].join('#');
  const encFlag = aesEncrypt(innerPlain);
  const b64Inner = Buffer.from(innerPlain).toString('base64');
  const outerPlain = [CFG.appKey, 'W', encFlag, 'W20220202', 'CLOUD', '0', '501', b64Inner].join('#');
  return aesEncrypt(outerPlain);
}
async function log2(sessionId, secretKey, ip, timestamp) {
  const data = log2Data(sessionId, secretKey, ip, timestamp);
  const p = { AccessKeyId: CFG.deviceKeyId, Version: '2020-10-15', SignatureMethod: 'HMAC-SHA1', SignatureVersion: '1.0', Format: 'JSON', Action: 'Log2', Data: data, SignatureNonce: uuid() };
  p.Signature = signOpenApi(p, CFG.deviceKeySecret);
  return postForm(deviceHost(), p);
}
async function initCaptcha() {
  const p = { AccessKeyId: CFG.captchaKeyId, SignatureMethod: 'HMAC-SHA1', SignatureVersion: '1.0', Format: 'JSON', Timestamp: timestampUTC(), Version: '2023-03-05', Action: 'InitCaptchaV3', SceneId: CFG.sceneId, Language: CFG.language, Mode: CFG.mode, DeviceData: deviceData('captcha-normal'), SignatureNonce: uuid() };
  p.Signature = signOpenApi(p, CFG.captchaKeySecret);
  return postForm(captchaHost(), p);
}
async function verifyCaptcha(certifyId, deviceToken) {
  const cvp = JSON.stringify({sceneId: CFG.sceneId, certifyId, deviceToken});
  const p = { AccessKeyId: CFG.captchaKeyId, SignatureMethod: 'HMAC-SHA1', SignatureVersion: '1.0', Format: 'JSON', Timestamp: timestampUTC(), Version: '2023-03-05', Action: 'VerifyCaptchaV3', SceneId: CFG.sceneId, CertifyId: certifyId, CaptchaVerifyParam: cvp, SignatureNonce: uuid() };
  p.Signature = signOpenApi(p, CFG.captchaKeySecret);
  return postForm(captchaHost(), p);
}
function buildCaptchaParam(certifyId, securityToken) {
  return Buffer.from(JSON.stringify({certifyId, sceneId: CFG.sceneId, isSign: true, securityToken}), 'utf8').toString('base64');
}
async function main() {
  const cmd = process.argv[2] || 'init';
  if (cmd === 'selftest') {
    const sample = {AccessKeyId: CFG.captchaKeyId,SignatureMethod:'HMAC-SHA1',SignatureVersion:'1.0',Format:'JSON',Timestamp:'2026-05-28T14:52:07Z',Version:'2023-03-05',Action:'InitCaptchaV3',SceneId:'didk33e0',Language:'en',Mode:'popup',DeviceData:'TEQYvgJq1LrMqFaBybfIzPxz2ygFyAct7X/w+LacfXWd9rGSwE/x6ZCONucD1fehS2Qpig6tUVsFK111d9wIk5pWp6rwYjzFCRgL7pNp8bzGsvOSdUXgQTopQm90YPSdl+BPPxh5tlQTA60lHQrH3a+Nm6VMtx2/5yKcSol4mRdtkrhcPDb8E7OxijXECHhg',SignatureNonce:'c2be9266-ea93-4a5a-9ba1-1afb16cc0032'};
    const sig = signOpenApi(sample, CFG.captchaKeySecret);
    console.log(JSON.stringify({signature_ok: sig === '4LFIZeDvoccRb611f+f68rbOd+w=', sig, log1DataPrefix: deviceData('captcha-front').slice(0,32), initDataPrefix: deviceData('captcha-normal').slice(0,32)}, null, 2));
    return;
  }
  if (cmd === 'parse-device') { const dc=process.argv[3]; if(!dc) throw new Error('usage: captcha_protocol.js parse-device <DeviceConfig>'); console.log(JSON.stringify(parseDeviceConfig(dc), null, 2)); return; }
  if (cmd === 'test-log2') {
    // Test: send Log2 with same Data format as Log1 (which works)
    const log1Data = deviceData('captcha-front');
    console.log('Log1 Data (works):', log1Data.slice(0, 60));
    // Try Log2 with Log1's Data
    const p1 = { AccessKeyId: CFG.deviceKeyId, Version: '2020-10-15', SignatureMethod: 'HMAC-SHA1', SignatureVersion: '1.0', Format: 'JSON', Action: 'Log2', Data: log1Data, SignatureNonce: uuid() };
    p1.Signature = signOpenApi(p1, CFG.deviceKeySecret);
    const r1 = await postForm(deviceHost(), p1);
    console.log('Log2 with Log1 Data:', JSON.stringify(r1));
    // Try Log2 with log2Data format
    const sessionId = process.argv[3] || 'test-session-id';
    const secretKey = process.argv[4] || 'testsecret';
    const ip = process.argv[5] || '1.2.3.4';
    const timestamp = process.argv[6] || String(Date.now());
    const log2D = log2Data(sessionId, secretKey, ip, timestamp);
    console.log('Log2 Data:', log2D.slice(0, 60));
    const p2 = { AccessKeyId: CFG.deviceKeyId, Version: '2020-10-15', SignatureMethod: 'HMAC-SHA1', SignatureVersion: '1.0', Format: 'JSON', Action: 'Log2', Data: log2D, SignatureNonce: uuid() };
    p2.Signature = signOpenApi(p2, CFG.deviceKeySecret);
    const r2 = await postForm(deviceHost(), p2);
    console.log('Log2 with log2Data:', JSON.stringify(r2));
    return;
  }
  if (cmd === 'log1') { console.log(JSON.stringify(await log1(), null, 2)); return; }
  if (cmd === 'log2') {
    const sessionId = process.argv[3], secretKey = process.argv[4], ip = process.argv[5] || '134.195.101.90', timestamp = process.argv[6] || String(Date.now());
    if (!sessionId || !secretKey) throw new Error('usage: captcha_protocol.js log2 <sessionId> <secretKey> [ip] [timestamp]');
    console.log(JSON.stringify(await log2(sessionId, secretKey, ip, timestamp), null, 2));
    return;
  }
  if (cmd === 'init') { console.log(JSON.stringify(await initCaptcha(), null, 2)); return; }
  if (cmd === 'mint') {
    const init = await initCaptcha();
    console.log(JSON.stringify({ok:false, stage:'feilin_deviceToken', init}, null, 2));
    process.exitCode = 2;
    return;
  }
  if (cmd === 'verify') {
    const certifyId = process.argv[3], deviceToken = process.argv[4];
    if (!certifyId || !deviceToken) throw new Error('usage: captcha_protocol.js verify <certifyId> <deviceToken>');
    const out = await verifyCaptcha(certifyId, deviceToken);
    if (out && out.Result && out.Result.securityToken) {
      const raw = buildCaptchaParam(out.Result.certifyId || certifyId, out.Result.securityToken);
      fs.writeFileSync(CACHE_FILE, JSON.stringify({captcha_verify_param: raw, ts: Math.floor(Date.now()/1000), source: 'captcha_protocol.js'}, null, 2));
      console.log(raw);
    } else console.log(JSON.stringify(out, null, 2));
    return;
  }
  throw new Error(`unknown command ${cmd}`);
}
main().catch(e => { console.error('[captcha_protocol]', e.stack || e.message); process.exit(1); });
