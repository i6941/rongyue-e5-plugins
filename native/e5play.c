/*
 * e5play —— B 站视频播放器的原生后端
 *
 * 为什么自己写：设备上的 ffmpeg / GStreamer 只有硬件解码器
 * (h264_v4l2m2m)，且没有 /dev/video*，等于没有 H.264 解码能力。
 * 这里自带 openh264 软解，解出来转成 RGB565，用和 e5emu 完全相同的
 * WebSocket 帧协议推给插件页面（4 字节头 + RGB565 像素）。
 *
 * 用法：
 *   ./e5play --selftest <file.mp4> [frames]      # 只解码+转码并测速
 *   ./e5play --serve <file.mp4> [port]           # 起 WebSocket 服务
 *   ./e5play --serve <file.mp4> 9511 --bind 0.0.0.0
 */
#define MINIMP4_IMPLEMENTATION
#include "minimp4.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <fcntl.h>

#include "wels/codec_api.h"

/* ---------------- 时间 ---------------- */

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1000.0 + (double)ts.tv_nsec / 1e6;
}

static void sleep_ms(double ms)
{
    if (ms <= 0) return;
    struct timespec ts;
    ts.tv_sec = (time_t)(ms / 1000.0);
    ts.tv_nsec = (long)((ms - (double)ts.tv_sec * 1000.0) * 1e6);
    while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {}
}

/* ---------------- SHA1 + base64（WebSocket 握手） ---------------- */

typedef struct { uint32_t h[5]; uint64_t len; uint8_t buf[64]; size_t n; } sha1_t;

static uint32_t rol(uint32_t v, int b) { return (v << b) | (v >> (32 - b)); }

static void sha1_block(sha1_t *s, const uint8_t *p)
{
    uint32_t w[80], a, b, c, d, e, f, k, t;
    for (int i = 0; i < 16; i++)
        w[i] = ((uint32_t)p[i * 4] << 24) | ((uint32_t)p[i * 4 + 1] << 16) |
               ((uint32_t)p[i * 4 + 2] << 8) | (uint32_t)p[i * 4 + 3];
    for (int i = 16; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3]; e = s->h[4];
    for (int i = 0; i < 80; i++) {
        if (i < 20) { f = (b & c) | ((~b) & d); k = 0x5A827999; }
        else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1; }
        else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC; }
        else { f = b ^ c ^ d; k = 0xCA62C1D6; }
        t = rol(a, 5) + f + e + k + w[i];
        e = d; d = c; c = rol(b, 30); b = a; a = t;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d; s->h[4] += e;
}

static void sha1_init(sha1_t *s)
{
    s->h[0] = 0x67452301; s->h[1] = 0xEFCDAB89; s->h[2] = 0x98BADCFE;
    s->h[3] = 0x10325476; s->h[4] = 0xC3D2E1F0; s->len = 0; s->n = 0;
}

static void sha1_update(sha1_t *s, const void *data, size_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    s->len += (uint64_t)len * 8;
    while (len--) {
        s->buf[s->n++] = *p++;
        if (s->n == 64) { sha1_block(s, s->buf); s->n = 0; }
    }
}

static void sha1_final(sha1_t *s, uint8_t out[20])
{
    uint64_t bits = s->len;
    uint8_t pad = 0x80;
    sha1_update(s, &pad, 1);
    uint8_t zero = 0;
    while (s->n != 56) sha1_update(s, &zero, 1);
    uint8_t lenbuf[8];
    for (int i = 0; i < 8; i++) lenbuf[i] = (uint8_t)(bits >> (56 - i * 8));
    sha1_update(s, lenbuf, 8);
    for (int i = 0; i < 5; i++) {
        out[i * 4] = (uint8_t)(s->h[i] >> 24);
        out[i * 4 + 1] = (uint8_t)(s->h[i] >> 16);
        out[i * 4 + 2] = (uint8_t)(s->h[i] >> 8);
        out[i * 4 + 3] = (uint8_t)s->h[i];
    }
}

static void b64_encode(const uint8_t *in, size_t len, char *out)
{
    static const char *tbl = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t i = 0, o = 0;
    while (i + 2 < len) {
        uint32_t v = ((uint32_t)in[i] << 16) | ((uint32_t)in[i + 1] << 8) | in[i + 2];
        out[o++] = tbl[(v >> 18) & 63]; out[o++] = tbl[(v >> 12) & 63];
        out[o++] = tbl[(v >> 6) & 63];  out[o++] = tbl[v & 63];
        i += 3;
    }
    if (i < len) {
        uint32_t v = (uint32_t)in[i] << 16;
        int rem = (int)(len - i);
        if (rem == 2) v |= (uint32_t)in[i + 1] << 8;
        out[o++] = tbl[(v >> 18) & 63]; out[o++] = tbl[(v >> 12) & 63];
        out[o++] = rem == 2 ? tbl[(v >> 6) & 63] : '=';
        out[o++] = '=';
    }
    out[o] = 0;
}

/* ---------------- WebSocket 服务端 ---------------- */

static int do_handshake(int fd)
{
    char req[4096];
    size_t got = 0;
    struct timeval rcv_to = { 5, 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &rcv_to, sizeof(rcv_to));
    while (got < sizeof(req) - 1) {
        ssize_t n = recv(fd, req + got, sizeof(req) - 1 - got, 0);
        if (n <= 0) return -1;
        got += (size_t)n;
        req[got] = 0;
        if (strstr(req, "\r\n\r\n")) break;
    }
    const char *key_hdr = strstr(req, "Sec-WebSocket-Key:");
    if (!key_hdr) return -2;
    key_hdr += strlen("Sec-WebSocket-Key:");
    while (*key_hdr == ' ') key_hdr++;
    const char *end = strstr(key_hdr, "\r\n");
    if (!end) return -2;
    char key[128];
    size_t klen = (size_t)(end - key_hdr);
    if (klen >= sizeof(key)) return -2;
    memcpy(key, key_hdr, klen);
    key[klen] = 0;

    char concat[256];
    snprintf(concat, sizeof(concat), "%s258EAFA5-E914-47DA-95CA-C5AB0DC85B11", key);
    sha1_t s;
    uint8_t digest[20];
    sha1_init(&s);
    sha1_update(&s, concat, strlen(concat));
    sha1_final(&s, digest);
    char accept[64];
    b64_encode(digest, 20, accept);

    char resp[512];
    int n = snprintf(resp, sizeof(resp),
                     "HTTP/1.1 101 Switching Protocols\r\n"
                     "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                     "Sec-WebSocket-Accept: %s\r\n\r\n", accept);
    return send(fd, resp, (size_t)n, 0) == n ? 0 : -3;
}

static int ws_send_frame(int fd, const uint8_t *hdr, size_t hdr_len, const uint8_t *pixels, size_t bytes)
{
    size_t total = bytes + hdr_len;
    uint8_t head[10];
    size_t hlen;
    head[0] = 0x82;
    if (total < 126) { head[1] = (uint8_t)total; hlen = 2; }
    else if (total < 65536) { head[1] = 126; head[2] = (uint8_t)(total >> 8); head[3] = (uint8_t)total; hlen = 4; }
    else {
        head[1] = 127;
        for (int i = 0; i < 8; i++) head[2 + i] = (uint8_t)((uint64_t)total >> (56 - i * 8));
        hlen = 10;
    }
    struct iovec iov[3];
    iov[0].iov_base = head; iov[0].iov_len = hlen;
    iov[1].iov_base = (void *)hdr; iov[1].iov_len = hdr_len;
    iov[2].iov_base = (void *)pixels; iov[2].iov_len = bytes;
    size_t want = hlen + hdr_len + bytes;
    size_t done = 0;
    while (done < want) {
        ssize_t r = writev(fd, iov, 3);
        if (r <= 0) return -1;
        done += (size_t)r;
        if (done >= want) break;
        size_t left = want - done;
        uint8_t *base[3] = { head, (uint8_t *)hdr, (uint8_t *)pixels };
        size_t len[3] = { hlen, hdr_len, bytes };
        int k = 0;
        for (int i = 0; i < 3; i++) {
            if (left >= len[i]) { base[i] += len[i]; left -= len[i]; }
            else { base[i] += left; len[i] -= left; left = 0; }
            if (len[i]) { iov[k].iov_base = base[i]; iov[k].iov_len = len[i]; k++; }
        }
        if (k == 0) break;
    }
    return 0;
}

static bool paused = false;
static volatile int g_seek_ms = -1;   /* >=0 表示待处理的跳转目标（毫秒） */

/* 读客户端命令；返回 -1 表示连接断了 */
static int ws_poll_cmd(int fd)
{
    uint8_t h[2];
    ssize_t n = recv(fd, h, 2, MSG_DONTWAIT);
    if (n <= 0) return n == 0 ? -1 : 0;
    size_t len = h[1] & 0x7f;
    bool masked = (h[1] & 0x80) != 0;
    uint8_t ext[8], mask[4] = {0};
    if (len == 126) { if (recv(fd, ext, 2, MSG_WAITALL) != 2) return -1; len = ((size_t)ext[0] << 8) | ext[1]; }
    else if (len == 127) { if (recv(fd, ext, 8, MSG_WAITALL) != 8) return -1; len = 0; }
    if (masked && recv(fd, mask, 4, MSG_WAITALL) != 4) return -1;
    uint8_t payload[16];
    if (len > sizeof(payload)) {
        uint8_t tmp[64];
        size_t left = len;
        while (left) {
            size_t chunk = left > sizeof(tmp) ? sizeof(tmp) : left;
            if (recv(fd, tmp, chunk, MSG_WAITALL) != (ssize_t)chunk) return -1;
            left -= chunk;
        }
        return 0;
    }
    if (len && recv(fd, payload, (size_t)len, MSG_WAITALL) != (ssize_t)len) return -1;
    for (size_t i = 0; i < len; i++) if (masked) payload[i] ^= mask[i & 3];
    uint8_t op = h[0] & 0x0f;
    if (op == 0x8) return -1;
    if (op >= 0x8) return 0;
    if (len >= 1 && payload[0] == 4) paused = !paused;   /* 和模拟器一致：4 = 暂停/继续 */
    if (len >= 5 && payload[0] == 5) {
        /* 5 = 跳到指定毫秒：u32 小端 */
        g_seek_ms = (int)((uint32_t)payload[1] | ((uint32_t)payload[2] << 8) |
                          ((uint32_t)payload[3] << 16) | ((uint32_t)payload[4] << 24));
    }
    return 0;
}

/* ---------------- MP4 解复用 ---------------- */

typedef struct {
    char path[512];
    FILE *f;
    int64_t size;
    MP4D_demux_t mp4;
    int vtrack;
    unsigned timescale;
    unsigned frames;
    unsigned width, height;
    uint8_t *sps;
    int sps_bytes;
    uint8_t *pps;
    int pps_bytes;
    int nal_len_size;
    uint8_t *sample;
    size_t sample_cap;
    uint8_t *annexb;
    size_t annexb_cap;
    /* 打开时把每个样本的时间戳/偏移/长度一次性取出来：
       MP4D_frame_offset 内部有顺序访问的缓存，随机 seek 不能直接反复调它。 */
    uint32_t *ts_ms;
    MP4D_file_offset_t *offs;
    uint32_t *sizes;
    unsigned base_ts;
} play_t;

static int mp4_read_cb(int64_t offset, void *buffer, size_t size, void *token)
{
    FILE *f = (FILE *)token;
#ifdef _WIN32
    if (_fseeki64(f, offset, SEEK_SET) != 0) return 1;
#else
    if (fseeko(f, (off_t)offset, SEEK_SET) != 0) return 1;
#endif
    /* minimp4 约定：返回 0 表示读成功，非 0 是错误 */
    return fread(buffer, 1, size, f) == size ? 0 : 1;
}

static void parse_avcc(play_t *p)
{
    /* minimp4 把 avcC 重排成：[numSPS][len][SPS]...[numPPS][len][PPS]...，
       不带最初的 version/profile/level/lengthSize 头，所以从 0 开始读。
       H.264 的 AVCC 长度字段实际都是 4 字节。 */
    const uint8_t *d = p->mp4.track[p->vtrack].dsi;
    unsigned n = p->mp4.track[p->vtrack].dsi_bytes;
    p->nal_len_size = 4;
    if (!d || n < 2) return;
    unsigned q = 0;
    int num_sps = d[q++];
    for (int i = 0; i < num_sps && q + 2 <= n; i++) {
        int ln = (d[q] << 8) | d[q + 1];
        q += 2;
        if (q + (unsigned)ln > n) break;
        if (!p->sps) { p->sps = (uint8_t *)malloc((size_t)ln); p->sps_bytes = ln; memcpy(p->sps, d + q, (size_t)ln); }
        q += (unsigned)ln;
    }
    if (q < n) {
        int num_pps = d[q++];
        for (int i = 0; i < num_pps && q + 2 <= n; i++) {
            int ln = (d[q] << 8) | d[q + 1];
            q += 2;
            if (q + (unsigned)ln > n) break;
            if (!p->pps) { p->pps = (uint8_t *)malloc((size_t)ln); p->pps_bytes = ln; memcpy(p->pps, d + q, (size_t)ln); }
            q += (unsigned)ln;
        }
    }
}

static bool play_open(play_t *p, const char *path)
{
    memset(p, 0, sizeof(*p));
    snprintf(p->path, sizeof(p->path), "%s", path);
    p->f = fopen(path, "rb");
    if (!p->f) { fprintf(stderr, "e5play: open %s failed\n", path); return false; }
#ifdef _WIN32
    _fseeki64(p->f, 0, SEEK_END);
    p->size = _ftelli64(p->f);
#else
    fseeko(p->f, 0, SEEK_END);
    p->size = (int64_t)ftello(p->f);
#endif
    if (!MP4D_open(&p->mp4, mp4_read_cb, p->f, p->size)) {
        fprintf(stderr, "e5play: not a valid mp4\n");
        return false;
    }
    p->vtrack = -1;
    for (unsigned i = 0; i < p->mp4.track_count; i++) {
        if (p->mp4.track[i].handler_type == MP4D_HANDLER_TYPE_VIDE) { p->vtrack = (int)i; break; }
    }
    if (p->vtrack < 0) { fprintf(stderr, "e5play: no video track\n"); return false; }
    MP4D_track_t *t = &p->mp4.track[p->vtrack];
    p->frames = t->sample_count;
    p->timescale = t->timescale ? t->timescale : 1000;
    p->width = t->SampleDescription.video.width;
    p->height = t->SampleDescription.video.height;
    parse_avcc(p);
    if (p->nal_len_size <= 0) p->nal_len_size = 4;

    p->ts_ms = (uint32_t *)calloc(p->frames ? p->frames : 1, sizeof(uint32_t));
    p->offs = (MP4D_file_offset_t *)calloc(p->frames ? p->frames : 1, sizeof(MP4D_file_offset_t));
    p->sizes = (uint32_t *)calloc(p->frames ? p->frames : 1, sizeof(uint32_t));
    if (!p->ts_ms || !p->offs || !p->sizes) return false;
    for (unsigned i = 0; i < p->frames; i++) {
        unsigned bytes = 0, ts = 0, dur = 0;
        MP4D_file_offset_t off = MP4D_frame_offset(&p->mp4, (unsigned)p->vtrack, i, &bytes, &ts, &dur);
        p->offs[i] = off;
        p->sizes[i] = bytes;
        p->ts_ms[i] = (uint32_t)((uint64_t)ts * 1000 / p->timescale);
    }
    p->base_ts = p->frames ? (unsigned)((uint64_t)p->ts_ms[0] * p->timescale / 1000) : 0;
    return true;
}

static void play_close(play_t *p)
{
    if (p->mp4.track) MP4D_close(&p->mp4);
    if (p->f) fclose(p->f);
    free(p->sps);
    free(p->pps);
    free(p->sample);
    free(p->annexb);
    free(p->ts_ms);
    free(p->offs);
    free(p->sizes);
}

/* 把 AVCC（长度前缀）样本转成 Annex-B，并按需在 IDR 前补 SPS/PPS */
static size_t sample_to_annexb(play_t *p, const uint8_t *src, size_t n, bool prepend_spspps)
{
    size_t need = n + 64 + (prepend_spspps ? (size_t)(p->sps_bytes + p->pps_bytes + 16) : 0);
    if (need > p->annexb_cap) {
        uint8_t *q = (uint8_t *)realloc(p->annexb, need);
        if (!q) return 0;
        p->annexb = q;
        p->annexb_cap = need;
    }
    uint8_t *out = p->annexb;
    size_t o = 0;
    if (prepend_spspps) {
        if (p->sps) {
            out[o++] = 0; out[o++] = 0; out[o++] = 0; out[o++] = 1;
            memcpy(out + o, p->sps, (size_t)p->sps_bytes); o += (size_t)p->sps_bytes;
        }
        if (p->pps) {
            out[o++] = 0; out[o++] = 0; out[o++] = 0; out[o++] = 1;
            memcpy(out + o, p->pps, (size_t)p->pps_bytes); o += (size_t)p->pps_bytes;
        }
    }
    size_t i = 0;
    int ls = p->nal_len_size;
    while (i + (size_t)ls <= n) {
        size_t ln = 0;
        for (int k = 0; k < ls; k++) ln = (ln << 8) | src[i + (size_t)k];
        i += (size_t)ls;
        if (!ln || i + ln > n) break;
        out[o++] = 0; out[o++] = 0; out[o++] = 0; out[o++] = 1;
        memcpy(out + o, src + i, ln);
        o += ln;
        i += ln;
    }
    return o;
}

static bool sample_is_idr(const uint8_t *src, size_t n, int ls)
{
    size_t i = 0;
    while (i + (size_t)ls <= n) {
        size_t ln = 0;
        for (int k = 0; k < ls; k++) ln = (ln << 8) | src[i + (size_t)k];
        i += (size_t)ls;
        if (!ln || i + ln > n) break;
        if ((src[i] & 0x1f) == 5) return true;
        i += ln;
    }
    return false;
}

/* ---------------- 音频（ffmpeg 解码 → 管道 → PulseAudio） ---------------- */

/* 设备上的 ffmpeg 有 aac 解码器，PulseAudio 在跑，paplay 可用。
   视频由我们自己解码，音频交给 ffmpeg：解成 48kHz 双声道 s16le，
   通过匿名管道直接喂给 paplay（用命名管道会在某个进程退出时把两边都卡住）。
   暂停/停止直接对这两个子进程发信号，声音和画面就能同时开始、同时停。 */
static pid_t g_audio_in = 0, g_audio_out = 0;
static bool g_audio_paused = false;

static void audio_stop(void)
{
    if (g_audio_in > 0) { kill(g_audio_in, SIGKILL); waitpid(g_audio_in, NULL, 0); g_audio_in = 0; }
    if (g_audio_out > 0) { kill(g_audio_out, SIGKILL); waitpid(g_audio_out, NULL, 0); g_audio_out = 0; }
    g_audio_paused = false;
}

static void audio_start(const char *path, double start_sec)
{
    audio_stop();
    int fds[2];
    if (pipe(fds) != 0) return;
    char ss[32];
    snprintf(ss, sizeof(ss), "%.3f", start_sec < 0 ? 0.0 : start_sec);

    pid_t out = fork();
    if (out == 0) {
        dup2(fds[0], 0);
        close(fds[0]); close(fds[1]);
        int nfd = open("/dev/null", O_WRONLY);
        if (nfd >= 0) { dup2(nfd, 1); dup2(nfd, 2); }
        execl("/usr/bin/paplay", "paplay", "--raw", "--format=s16le",
              "--rate=48000", "--channels=2", (char *)NULL);
        _exit(127);
    }
    pid_t in = fork();
    if (in == 0) {
        dup2(fds[1], 1);
        close(fds[0]); close(fds[1]);
        int nfd = open("/dev/null", O_WRONLY);
        if (nfd >= 0) dup2(nfd, 2);
        execl("/usr/bin/ffmpeg", "ffmpeg", "-v", "error", "-ss", ss, "-i", path,
              "-map", "0:a:0", "-vn", "-sn", "-dn", "-f", "s16le",
              "-ac", "2", "-ar", "48000", "-", (char *)NULL);
        _exit(127);
    }
    close(fds[0]);
    close(fds[1]);
    if (out > 0) g_audio_out = out;
    if (in > 0) g_audio_in = in;
}

static void audio_set_paused(bool p)
{
    if (!g_audio_in || g_audio_paused == p) return;
    g_audio_paused = p;
    int sig = p ? SIGSTOP : SIGCONT;
    if (g_audio_in > 0) kill(g_audio_in, sig);
    if (g_audio_out > 0) kill(g_audio_out, sig);
}

/* ---------------- YUV420 -> RGB565（带缩放） ---------------- */

typedef struct {
    int ow, oh;
    int *xmap;
    int *ymap;
    uint8_t *out;      /* RGB565 小端 */
} scaler_t;

static void scaler_init(scaler_t *s, int src_w, int src_h, int max_w, int max_h)
{
    memset(s, 0, sizeof(*s));
    int ow = src_w, oh = src_h;
    if (ow > max_w) { oh = (int)((int64_t)oh * max_w / ow); ow = max_w; }
    if (oh > max_h) { ow = (int)((int64_t)ow * max_h / oh); oh = max_h; }
    if (ow < 2) ow = 2;
    if (oh < 2) oh = 2;
    ow &= ~1;
    oh &= ~1;
    s->ow = ow;
    s->oh = oh;
    s->xmap = (int *)malloc(sizeof(int) * (size_t)ow);
    s->ymap = (int *)malloc(sizeof(int) * (size_t)oh);
    for (int x = 0; x < ow; x++) s->xmap[x] = x * src_w / ow;
    for (int y = 0; y < oh; y++) s->ymap[y] = y * src_h / oh;
    s->out = (uint8_t *)malloc((size_t)ow * (size_t)oh * 2);
}

static void scaler_free(scaler_t *s)
{
    free(s->xmap);
    free(s->ymap);
    free(s->out);
    memset(s, 0, sizeof(*s));
}

static void yuv_to_rgb565(const scaler_t *s, const uint8_t *yp, const uint8_t *up, const uint8_t *vp,
                          int ys, int cs, uint16_t *dst)
{
    for (int y = 0; y < s->oh; y++) {
        int sy = s->ymap[y];
        const uint8_t *yr = yp + (size_t)sy * ys;
        const uint8_t *ur = up + (size_t)(sy >> 1) * cs;
        const uint8_t *vr = vp + (size_t)(sy >> 1) * cs;
        uint16_t *orow = dst + (size_t)y * s->ow;
        for (int x = 0; x < s->ow; x++) {
            int sx = s->xmap[x];
            int Y = (int)yr[sx] - 16;
            int U = (int)ur[sx >> 1] - 128;
            int V = (int)vr[sx >> 1] - 128;
            int R = (298 * Y + 409 * V + 128) >> 8;
            int G = (298 * Y - 100 * U - 208 * V + 128) >> 8;
            int B = (298 * Y + 516 * U + 128) >> 8;
            if (R < 0) R = 0; else if (R > 255) R = 255;
            if (G < 0) G = 0; else if (G > 255) G = 255;
            if (B < 0) B = 0; else if (B > 255) B = 255;
            orow[x] = (uint16_t)(((R & 0xF8) << 8) | ((G & 0xFC) << 3) | (B >> 3));
        }
    }
}

/* ---------------- 解码循环 ---------------- */

typedef struct {
    play_t *p;
    ISVCDecoder *dec;
    scaler_t sc;
    unsigned w, h;
    unsigned frame_no;
} player_t;

static bool player_open(player_t *pl, play_t *p, int max_w, int max_h)
{
    memset(pl, 0, sizeof(*pl));
    pl->p = p;
    if (WelsCreateDecoder(&pl->dec) != 0 || !pl->dec) {
        fprintf(stderr, "e5play: WelsCreateDecoder failed\n");
        return false;
    }
    SDecodingParam dp;
    memset(&dp, 0, sizeof(dp));
    dp.sVideoProperty.eVideoBsType = VIDEO_BITSTREAM_AVC;
    dp.eEcActiveIdc = ERROR_CON_SLICE_COPY;
    if (pl->dec->Initialize(&dp) != 0) {
        fprintf(stderr, "e5play: decoder init failed\n");
        return false;
    }
    return true;
}

/* 解码一个样本；返回 0 表示正常。有新帧时通过 out 拿 RGB565 与小尺寸 */
static int player_decode_sample(player_t *pl, unsigned idx, const uint8_t **rgb, int *ow, int *oh, double *pts_ms)
{
    play_t *p = pl->p;
    if (idx >= p->frames) return 6;
    unsigned frame_bytes = p->sizes[idx];
    MP4D_file_offset_t off = p->offs[idx];
    if (!frame_bytes) return 1;
    if (frame_bytes > p->sample_cap) {
        uint8_t *q = (uint8_t *)realloc(p->sample, frame_bytes);
        if (!q) return 2;
        p->sample = q;
        p->sample_cap = frame_bytes;
    }
    if (mp4_read_cb((int64_t)off, p->sample, frame_bytes, p->f)) return 3;

    bool idr = sample_is_idr(p->sample, frame_bytes, p->nal_len_size);
    size_t n = sample_to_annexb(p, p->sample, frame_bytes, idr || idx == 0);
    if (!n) return 4;

    /* 整个样本（一个访问单元）一次送进解码器：
       逐个 NAL 送会被当成不完整的访问单元，带 B 帧的片子会报参考丢失。 */
    unsigned char *plane[3] = { 0, 0, 0 };
    SBufferInfo info;
    memset(&info, 0, sizeof(info));
    pl->dec->DecodeFrameNoDelay(p->annexb, (int)n, plane, &info);
    if (info.iBufferStatus == 1) {
        unsigned w = (unsigned)info.UsrData.sSystemBuffer.iWidth;
        unsigned h = (unsigned)info.UsrData.sSystemBuffer.iHeight;
        if (w && h) {
            if (w != pl->w || h != pl->h || !pl->sc.out) {
                pl->w = w; pl->h = h;
                if (!pl->sc.out) scaler_init(&pl->sc, (int)w, (int)h, 320, 480);
            }
            if (pl->sc.out) {
                yuv_to_rgb565(&pl->sc, plane[0], plane[1], plane[2],
                              info.UsrData.sSystemBuffer.iStride[0],
                              info.UsrData.sSystemBuffer.iStride[1],
                              (uint16_t *)pl->sc.out);
                *rgb = pl->sc.out;
                *ow = pl->sc.ow;
                *oh = pl->sc.oh;
                pl->frame_no++;
                if (pts_ms) *pts_ms = (double)p->ts_ms[idx];
                return 0;
            }
        }
    }
    return 5;
}

/* 跳转后必须重建解码器：旧的状态里还留着上一段的参考帧 */
static bool player_reset(player_t *pl)
{
    if (pl->dec) {
        pl->dec->Uninitialize();
        WelsDestroyDecoder(pl->dec);
        pl->dec = NULL;
    }
    if (WelsCreateDecoder(&pl->dec) != 0 || !pl->dec) return false;
    SDecodingParam dp;
    memset(&dp, 0, sizeof(dp));
    dp.sVideoProperty.eVideoBsType = VIDEO_BITSTREAM_AVC;
    dp.eEcActiveIdc = ERROR_CON_SLICE_COPY;
    return pl->dec->Initialize(&dp) == 0;
}

static void player_close(player_t *pl)
{
    if (pl->dec) {
        pl->dec->Uninitialize();
        WelsDestroyDecoder(pl->dec);
        pl->dec = NULL;
    }
    scaler_free(&pl->sc);
}

/* ---------------- 自测 ---------------- */

static int run_selftest(const char *path, long frames)
{
    play_t p;
    if (!play_open(&p, path)) return 3;
    printf("E5PLAY mp4=%s track=%d frames=%u geometry=%ux%u timescale=%u len_size=%d sps=%d pps=%d\n",
           path, p.vtrack, p.frames, p.width, p.height, p.timescale, p.nal_len_size, p.sps_bytes, p.pps_bytes);
    fflush(stdout);

    player_t pl;
    if (!player_open(&pl, &p, 320, 480)) return 4;

    long done = 0, produced = 0;
    double t0 = now_ms();
    for (unsigned i = 0; i < p.frames && done < frames; i++, done++) {
        const uint8_t *rgb = NULL;
        int ow = 0, oh = 0;
        int rc = player_decode_sample(&pl, i, &rgb, &ow, &oh, NULL);
        if (rc == 0 && rgb) produced++;
    }
    double ms = now_ms() - t0;
    printf("E5PLAY samples=%ld frames=%ld out=%ux%u elapsed_ms=%.1f fps=%.2f\n",
           done, produced, pl.sc.ow, pl.sc.oh, ms, ms > 0 ? produced * 1000.0 / ms : 0.0);
    player_close(&pl);
    play_close(&p);
    return 0;
}

/* ---------------- 服务模式 ---------------- */

static const char *g_bind_addr = "127.0.0.1";

/* 从目标样本往前找最近的 IDR：解码器必须从关键帧重新开始才不会有花块 */
static unsigned find_idr_at_or_before(play_t *p, unsigned idx)
{
    unsigned lo = idx > 900 ? idx - 900 : 0;
    for (unsigned i = idx + 1; i-- > lo; ) {
        if (!p->sizes[i]) continue;
        if (p->sizes[i] > p->sample_cap) {
            uint8_t *q = (uint8_t *)realloc(p->sample, p->sizes[i]);
            if (!q) return idx;
            p->sample = q;
            p->sample_cap = p->sizes[i];
        }
        if (mp4_read_cb((int64_t)p->offs[i], p->sample, p->sizes[i], p->f) != 0) continue;
        if (sample_is_idr(p->sample, p->sizes[i], p->nal_len_size)) return i;
    }
    return idx;
}

/* 时间（毫秒）→ 样本序号，二分查找 */
static unsigned sample_for_ms(const play_t *p, unsigned ms)
{
    unsigned lo = 0, hi = p->frames;
    while (lo < hi) {
        unsigned mid = lo + (hi - lo) / 2;
        if (p->ts_ms[mid] < ms) lo = mid + 1; else hi = mid;
    }
    return lo < p->frames ? lo : (p->frames ? p->frames - 1 : 0);
}

static int run_server(const char *path, int port)
{
    play_t p;
    if (!play_open(&p, path)) return 3;
    printf("E5PLAY mp4=%s frames=%u geometry=%ux%u timescale=%u\n",
           path, p.frames, p.width, p.height, p.timescale);
    fflush(stdout);

    int ls = socket(AF_INET, SOCK_STREAM, 0);
    if (ls < 0) { perror("socket"); return 5; }
    int one = 1;
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    if (!strcmp(g_bind_addr, "0.0.0.0") || !strcmp(g_bind_addr, "*"))
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
    else
        addr.sin_addr.s_addr = inet_addr(g_bind_addr);
    addr.sin_port = htons((uint16_t)port);
    if (bind(ls, (struct sockaddr *)&addr, sizeof(addr)) < 0) { perror("bind"); close(ls); return 5; }
    if (listen(ls, 4) < 0) { perror("listen"); close(ls); return 5; }
    printf("E5PLAY listening %s:%d\n", g_bind_addr, port);
    fflush(stdout);

    for (;;) {
        struct pollfd pfd;
        pfd.fd = ls; pfd.events = POLLIN; pfd.revents = 0;
        int pr = poll(&pfd, 1, 120000);
        if (pr == 0) { fprintf(stderr, "E5PLAY idle 120s, exiting\n"); break; }
        if (pr < 0) { if (errno == EINTR) continue; break; }
        int cfd = accept(ls, NULL, NULL);
        if (cfd < 0) { if (errno == EINTR) continue; break; }
        setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        struct timeval snd_to = { 2, 0 };
        setsockopt(cfd, SOL_SOCKET, SO_SNDTIMEO, &snd_to, sizeof(snd_to));
        if (do_handshake(cfd) != 0) { close(cfd); continue; }
        printf("E5PLAY client connected\n");
        fflush(stdout);

        player_t pl;
        if (!player_open(&pl, &p, 320, 480)) { close(cfd); break; }
        paused = false;
        g_seek_ms = -1;

        double start = now_ms();
        unsigned idx = 0;
        double seek_until = 0.0;
        unsigned long sent = 0;
        audio_start(p.path, 0.0);

        while (1) {
            if (ws_poll_cmd(cfd) < 0) break;
            audio_set_paused(paused);

            if (g_seek_ms >= 0) {
                unsigned target_ms = (unsigned)g_seek_ms;
                g_seek_ms = -1;
                if (target_ms >= p.ts_ms[p.frames - 1]) break;   /* 跳到结尾 */
                idx = find_idr_at_or_before(&p, sample_for_ms(&p, target_ms));
                player_reset(&pl);
                seek_until = (double)target_ms;
                start = now_ms() - (double)target_ms;
                audio_stop();
                audio_start(p.path, (double)target_ms / 1000.0);
                printf("E5PLAY seek %ums sample=%u\n", target_ms, idx);
                fflush(stdout);
            }

            if (paused) { sleep_ms(20); continue; }

            double target = (double)p.ts_ms[idx];
            double wait = start + target - now_ms();
            if (wait > 0) sleep_ms(wait > 100 ? 100 : wait);

            const uint8_t *rgb = NULL;
            int ow = 0, oh = 0;
            double pts = 0.0;
            player_decode_sample(&pl, idx, &rgb, &ow, &oh, &pts);
            if (rgb && ow > 0 && oh > 0 && pts + 1.0 >= seek_until) {
                unsigned ms = (unsigned)(pts + 0.5);
                uint8_t hdr[8] = { (uint8_t)(ow & 0xff), (uint8_t)(ow >> 8),
                                   (uint8_t)(oh & 0xff), (uint8_t)(oh >> 8),
                                   (uint8_t)(ms & 0xff), (uint8_t)((ms >> 8) & 0xff),
                                   (uint8_t)((ms >> 16) & 0xff), (uint8_t)((ms >> 24) & 0xff) };
                if (ws_send_frame(cfd, hdr, sizeof(hdr), rgb, (size_t)ow * (size_t)oh * 2) != 0) break;
                sent++;
                seek_until = 0.0;
            }
            idx++;
            if (idx >= p.frames) break;   /* 放完就结束 */
        }

        printf("E5PLAY client disconnected, frames=%lu\n", sent);
        fflush(stdout);
        audio_stop();
        player_close(&pl);
        close(cfd);
    }

    close(ls);
    play_close(&p);
    return 0;
}

int main(int argc, char **argv)
{
    const char *path = NULL;
    bool selftest = false, serve = false;
    long frames = 600;
    int port = 9511;

    signal(SIGPIPE, SIG_IGN);

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--selftest")) selftest = true;
        else if (!strcmp(argv[i], "--serve")) serve = true;
        else if (!strcmp(argv[i], "--bind") && i + 1 < argc) g_bind_addr = argv[++i];
        else if (!path) path = argv[i];
        else {
            /* 两种模式共用位置参数：自测模式是帧数，服务模式是端口。
               之前统一按“>100 就是帧数”判断，导致 --serve 传端口被吃掉。 */
            long v = atol(argv[i]);
            if (v <= 0 || v > 65535) continue;
            if (serve) port = (int)v; else frames = v;
        }
    }
    if (!path || (!selftest && !serve)) {
        fprintf(stderr,
                "usage: e5play --selftest <file.mp4> [frames]\n"
                "       e5play --serve <file.mp4> [port] [--bind <addr>]\n");
        return 2;
    }
    return serve ? run_server(path, port) : run_selftest(path, frames);
}
