/* 在 Node 里跑输入法引擎：不需要浏览器，只验证「按键 -> 候选 -> 上屏」。 */
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');

function stubEl() {
  return {
    textContent: '',
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    appendChild() {},
    setAttribute() {},
    addEventListener() {},
    value: ''
  };
}

global.window = global;
global.document = { getElementById: () => stubEl(), createElement: () => stubEl() };
global.setTimeout = (fn, ms) => 0;
global.clearTimeout = () => {};
global.Date = Date;

eval(fs.readFileSync(path.join(root, 'plugins/bili/ime-dict.js'), 'utf8'));
eval(fs.readFileSync(path.join(root, 'plugins/bili/ime.js'), 'utf8'));

const IME = global.E5IME;
IME.init({ search() {} });

function type(keys) {
  for (const k of keys) IME.key('digit', k);
}

function case_(name, keys, expectTop) {
  IME.open('');
  type(keys);
  const cands = IME.cands().slice(0, 8);
  const ok = expectTop.every((want, i) => cands[i] === want);
  console.log((ok ? 'OK   ' : 'FAIL ') + name + '  ' + keys.join('') + ' -> ' + cands.join(' '));
  return ok;
}

let bad = 0;
for (const [name, keys, want] of [
  ['你好', '64426'.split(''), ['你好']],
  ['音乐', '946983'.split(''), ['音乐']],
  ['视频', '744746'.split(''), ['视频', '食品']],
  ['下载', '942924'.split(''), ['下载']],
  ['推荐', '8845426'.split(''), ['推荐']],
  ['连打：你好世界', '64426744543'.split(''), ['你好世界']],
  ['连打：视频推荐', '7447468845426'.split(''), ['视频推荐']],
  ['连打：番剧弹幕', '3265832668'.split(''), ['番剧弹幕']],
  ['字幕', '9468'.split(''), ['字幕']],
  ['单字 你', '64'.split(''), ['你']]
]) {
  if (want) { if (!case_(name, keys, want)) bad++; }
  else {
    IME.open('');
    type(keys);
    console.log('INFO ' + name + ' -> ' + IME.cands().slice(0, 6).join(' '));
  }
}

// 上屏 + 连续输入两个词 + 退格
IME.open('');
type('64426'.split(''));
IME.key('ok');
type('946983'.split(''));
IME.key('ok');
console.log((IME.text() === '你好音乐' ? 'OK   ' : 'FAIL ') + '连续输入上屏 -> ' + IME.text());
IME.key('back');
console.log((IME.text() === '你好音' ? 'OK   ' : 'FAIL ') + '退格 -> ' + IME.text());

// 候选移动
IME.open('');
type('64'.split(''));
const first = IME.selected();
IME.key('right', '');
const second = IME.selected();
console.log((first !== second ? 'OK   ' : 'FAIL ') + '右移选字 ' + first + ' -> ' + second);

process.exit(bad ? 1 : 0);
