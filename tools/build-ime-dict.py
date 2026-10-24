"""把 jieba 词频表 + pinyin-data 注音表编译成设备用的 9 键拼音词典。

为什么要自己编译：设备自带的 pinyin9 只有 676 条词，打什么都要翻页选字。
这里用两份 MIT 许可的数据（允许随插件分发）：

  * jieba/dict.txt                 词 + 词频（决定候选顺序）
  * pinyin-data/pinyin.txt         单字注音
  * phrase-pinyin-data/large_pinyin.txt  词组注音（解决多音字）

输出 plugins/bili/ime-dict.js：一张「数字签名 -> 词」表，页面只管查表，
不用在设备上算拼音。

用法：
    python tools/build-ime-dict.py --jieba <dict.txt> --pinyin <pinyin.txt> \
        --phrase <large_pinyin.txt> [--words 24000] [--out plugins/bili/ime-dict.js]

数据下载（任选一个镜像）：
    https://raw.githubusercontent.com/fxsjy/jieba/master/jieba/dict.txt
    https://raw.githubusercontent.com/mozillazg/pinyin-data/master/pinyin.txt
    https://raw.githubusercontent.com/mozillazg/phrase-pinyin-data/master/large_pinyin.txt
"""
import argparse
import math
import re
import unicodedata
from pathlib import Path

T9 = {}
for _d, _letters in ('2', 'abc'), ('3', 'def'), ('4', 'ghi'), ('5', 'jkl'), ('6', 'mno'), \
                    ('7', 'pqrs'), ('8', 'tuv'), ('9', 'wxyz'):
    for _ch in _letters:
        T9[_ch] = _d
T9['v'] = '8'  # ü 写作 v

HAN = re.compile(r'^[\u3400-\u9fff]+$')


def plain(pinyin):
    """带声调的音节 -> 纯字母（ü 变 v）。

    注意顺序：必须先把 ü / ǖǘǚǜ 换成 v，再去掉声调符号。
    直接 NFD 去组合符会把 ü 拆成 u + 两点，结果「女」被当成 ni。
    """
    s = pinyin.replace('ü', 'v').replace('Ü', 'v')
    for accented in 'ǖǘǚǜ':
        s = s.replace(accented, 'v')
    s = s.replace('u:', 'v').replace('U:', 'v')
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ''.join(c for c in s.lower() if c.isalpha())


def signature(syllables):
    """['ni','hao'] -> '64426'；含非法字母返回 None。"""
    out = []
    for syl in syllables:
        for ch in syl:
            d = T9.get(ch)
            if not d:
                return None
            out.append(d)
    return ''.join(out) if out else None


def load_chars(path):
    """U+4E00: yī, yí  ->  {字: 'yi'}（取第一个读音）"""
    chars = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^U\+([0-9A-Fa-f]+):\s*([^#]+)', line)
        if not m:
            continue
        ch = chr(int(m.group(1), 16))
        if not HAN.match(ch):
            continue
        first = m.group(2).split(',')[0].strip()
        syl = plain(first)
        if syl:
            chars[ch] = syl
    return chars


def load_phrases(path):
    """词: xié dú  ->  {词: 'xie du'}"""
    phrases = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        head, _, tail = line.partition(':')
        word = head.strip()
        if not word or not HAN.match(word):
            continue
        syls = [plain(s) for s in tail.split()]
        if len(syls) != len(word) or not all(syls):
            continue
        phrases[word] = ' '.join(syls)
    return phrases


def load_words(path, chars, phrases, max_words, max_len=4):
    """jieba 词频表 -> [(词, 音节列表, 词频)]，只保留纯汉字、长度 2..max_len。"""
    out = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        parts = line.split(' ')
        if len(parts) < 2:
            continue
        word = parts[0]
        if not HAN.match(word) or not (2 <= len(word) <= max_len):
            continue
        try:
            freq = int(parts[1])
        except ValueError:
            continue
        if freq < 2:
            continue
        py = phrases.get(word)
        if py:
            syls = py.split(' ')
        else:
            syls = [chars.get(c) for c in word]
            if not all(syls):
                continue
        out.append((word, syls, freq))
    out.sort(key=lambda t: -t[2])
    return out[:max_words]


def load_single_chars(path, chars, min_freq=2):
    out = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        parts = line.split(' ')
        if len(parts) < 2 or len(parts[0]) != 1:
            continue
        ch = parts[0]
        if not HAN.match(ch):
            continue
        try:
            freq = int(parts[1])
        except ValueError:
            continue
        syl = chars.get(ch)
        if syl and freq >= min_freq:
            out.append((ch, [syl], freq))
    out.sort(key=lambda t: -t[2])
    return out


def add(entries, sig_map, word, syls, bucket):
    sig = signature(syls)
    if not sig or len(sig) > 14:
        return
    bucket = max(1, min(9, bucket))
    group = sig_map.setdefault(sig, [])
    for item in group:
        if item[0] == word:
            if bucket > item[1]:
                item[1] = bucket
            return
    group.append([word, bucket])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jieba', required=True)
    ap.add_argument('--pinyin', required=True)
    ap.add_argument('--phrase', required=True)
    ap.add_argument('--words', type=int, default=24000)
    ap.add_argument('--chars', type=int, default=6000)
    ap.add_argument('--per-sig', type=int, default=12)
    ap.add_argument('--out', default='plugins/bili/ime-dict.js')
    args = ap.parse_args()

    # 通用词频里「食品」比「视频」高，但这个输入法主要用来搜视频，
    # 把站内高频词直接抬到最高档，省得每次都要翻页
    boost = set('''视频 番剧 弹幕 字幕 直播 动画 鬼畜 音乐 舞蹈 游戏 科技 数码 影视
        综艺 纪录片 推荐 热门 排行 搜索 关注 收藏 硬币 分享 投币 播放 点赞 评论 转发
        合集 分集 连载 完结 预告 花絮 剪辑 混剪 解说 评测 教程 学习 公开课 纪录片'''.split())

    # jieba 里没有、但在这个 app 里天天要打的词。拼音不写空格也行，
    # 签名只看字母本身（zimu -> 9468）
    extra = [
        ('番剧', 'fanju'), ('弹幕', 'danmu'), ('字幕', 'zimu'), ('鬼畜', 'guichu'),
        ('混剪', 'hunjian'), ('追番', 'zhuifan'), ('补番', 'bufan'), ('三连', 'sanlian'),
        ('投币', 'toubi'), ('专栏', 'zhuanlan'), ('专栏', 'zhuanlan'), ('分集', 'fenji'),
        ('合集', 'heji'), ('连载', 'lianzai'), ('up主', 'upzhu'), ('番外', 'fanwai'),
        ('中字', 'zhongzi'), ('生肉', 'shengrou'), ('熟肉', 'shurou'), ('横屏', 'hengping'),
        ('竖屏', 'shuping'), ('倍速', 'beisu'), ('弹窗', 'danchuang'), ('片头', 'piantou'),
    ]

    chars = load_chars(args.pinyin)
    phrases = load_phrases(args.phrase)
    words = load_words(args.jieba, chars, phrases, args.words)
    singles = load_single_chars(args.jieba, chars)[:args.chars]

    allf = [f for _, _, f in words] + [f for _, _, f in singles]
    lo, hi = math.log(min(allf)), math.log(max(allf))

    def bucket(freq):
        return 1 + int(8 * (math.log(freq) - lo) / (hi - lo + 1e-9))

    sig_map = {}
    for word, syls, freq in words:
        add(None, sig_map, word, syls, 9 if word in boost else bucket(freq))
    for ch, syls, freq in singles:
        add(None, sig_map, ch, syls, bucket(freq))
    for word, py in extra:
        add(None, sig_map, word, [py], 9)

    # 每个签名只留前 N 个词：词库大不等于好用，翻页多了更难选
    total = 0
    rows = []
    for sig in sorted(sig_map):
        group = sorted(sig_map[sig], key=lambda it: -it[1])[:args.per_sig]
        total += len(group)
        rows.append(sig + '|' + ','.join(w + '~' + str(b) for w, b in group))

    body = ';'.join(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '/* 9 键拼音词典（由 tools/build-ime-dict.py 生成，勿手改）\n'
        ' * 数据：jieba dict.txt（词频，MIT）、mozillazg/pinyin-data（注音，MIT）\n'
        ' * 格式：数字签名|词~词频档,词~词频档;...\n'
        ' */\n'
        'window.IME_DICT = "' + body + '";\n',
        encoding='utf-8')
    print('词条 %d，签名 %d，文件 %d 字节 -> %s' % (total, len(rows), out.stat().st_size, out))


if __name__ == '__main__':
    main()
