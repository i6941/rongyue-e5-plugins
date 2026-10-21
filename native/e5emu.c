/* e5emu — E5 上的原生 libretro 前端
 *
 * 阶段 2：WebSocket 推帧 + 收按键。
 *   - 默认只监听回环地址，端口 9510；
 *   - 有客户端连上才跑模拟器（按需运行），客户端断开后停止并等待；
 *   - 每帧发一个二进制帧：4 字节头（宽、高，各 u16 小端）+ RGB565 像素；
 *   - 客户端发 4 字节按键位图（u32 小端），按 libretro 的按钮编号置位。
 *
 * 编译（在电脑上交叉编译，目标 aarch64 musl）：
 *   zig cc -target aarch64-linux-musl -O2 -static e5emu.c <core sources> -o e5emu
 *
 * 用法：
 *   ./e5emu --selftest <rom.nes> [帧数]     # 只跑基准，不联网
 *   ./e5emu --serve <rom.nes> [端口]        # 启动 WebSocket 服务
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>

#include "libretro.h"

/* ---------------- libretro 回调 ---------------- */

static unsigned buttons = 0;
static const void *last_frame = NULL;
static unsigned last_w = 0, last_h = 0;
static size_t last_pitch = 0;
static unsigned long frame_counter = 0;
static enum retro_pixel_format pixfmt = RETRO_PIXEL_FORMAT_0RGB1555;
static uint8_t *frame_copy = NULL;
static size_t frame_copy_cap = 0;

static bool env_cb(unsigned cmd, void *data)
{
    switch (cmd) {
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
        if (data) pixfmt = *(const enum retro_pixel_format *)data;
        return true;
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        if (data) *(const char **)data = ".";
        return true;
    case RETRO_ENVIRONMENT_GET_CAN_DUPE:
        if (data) *(bool *)data = true;
        return true;
    case RETRO_ENVIRONMENT_GET_VARIABLE:
        if (data) ((struct retro_variable *)data)->value = NULL;
        return false;
    case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
        if (data) *(bool *)data = false;
        return true;
    case RETRO_ENVIRONMENT_GET_LANGUAGE:
        if (data) *(unsigned *)data = RETRO_LANGUAGE_ENGLISH;
        return true;
    case RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE:
        if (data) *(int *)data = 3;
        return true;
    case RETRO_ENVIRONMENT_GET_FASTFORWARDING:
        if (data) *(bool *)data = false;
        return true;
    case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
    case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
    case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:
    case RETRO_ENVIRONMENT_SET_GEOMETRY:
    case RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS:
    case RETRO_ENVIRONMENT_SET_SERIALIZATION_QUIRKS:
        return true;
    default:
        return false;
    }
}

static void video_cb(const void *data, unsigned width, unsigned height, size_t pitch)
{
    last_frame = data;
    last_w = width;
    last_h = height;
    last_pitch = pitch;
    frame_counter++;
}

static void audio_sample_cb(int16_t left, int16_t right) { (void)left; (void)right; }
static size_t audio_batch_cb(const int16_t *data, size_t frames) { (void)data; return frames; }
static void input_poll_cb(void) { }

static int16_t input_state_cb(unsigned port, unsigned device, unsigned index, unsigned id)
{
    (void)device; (void)index;
    if (port != 0 || id >= 16) return 0;
    return (int16_t)((buttons >> id) & 1u);
}

/* ---------------- SHA1 + base64（WebSocket 握手用） ---------------- */

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

static int ws_send_frame(int fd, const uint8_t *hdr4, const uint8_t *pixels, size_t bytes)
{
    size_t total = bytes + 4;
    uint8_t head[10];
    size_t hlen;
    head[0] = 0x82;                 /* FIN + binary */
    if (total < 126) { head[1] = (uint8_t)total; hlen = 2; }
    else if (total < 65536) { head[1] = 126; head[2] = (uint8_t)(total >> 8); head[3] = (uint8_t)total; hlen = 4; }
    else {
        head[1] = 127;
        for (int i = 0; i < 8; i++) head[2 + i] = (uint8_t)((uint64_t)total >> (56 - i * 8));
        hlen = 10;
    }
    uint8_t meta[4] = { hdr4[0], hdr4[1], hdr4[2], hdr4[3] };
    struct iovec iov[3];
    iov[0].iov_base = head; iov[0].iov_len = hlen;
    iov[1].iov_base = meta; iov[1].iov_len = 4;
    iov[2].iov_base = (void *)pixels; iov[2].iov_len = bytes;
    ssize_t r = writev(fd, iov, 3);
    return r == (ssize_t)(hlen + 4 + bytes) ? 0 : -1;
}

/* 读客户端来的按键位图（4 字节，带掩码） */
static int ws_read_buttons(int fd)
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
    if (len > sizeof(payload)) { uint8_t tmp[64]; size_t left = len; while (left) { size_t chunk = left > sizeof(tmp) ? sizeof(tmp) : left; if (recv(fd, tmp, chunk, MSG_WAITALL) != (ssize_t)chunk) return -1; left -= chunk; } return 0; }
    if (len && recv(fd, payload, (size_t)len, MSG_WAITALL) != (ssize_t)len) return -1;
    for (size_t i = 0; i < len; i++) if (masked) payload[i] ^= mask[i & 3];
    if (h[0] & 0x0f) { /* 控制帧：忽略（ping/close 由客户端重连处理） */ return 0; }
    if (len >= 4) buttons = (uint32_t)payload[0] | ((uint32_t)payload[1] << 8) |
                             ((uint32_t)payload[2] << 16) | ((uint32_t)payload[3] << 24);
    return 0;
}

/* ---------------- 工具 ---------------- */

static void *read_file(const char *path, size_t *out_size)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long n = ftell(f);
    if (n <= 0) { fclose(f); return NULL; }
    rewind(f);
    void *buf = malloc((size_t)n);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) { free(buf); fclose(f); return NULL; }
    fclose(f);
    *out_size = (size_t)n;
    return buf;
}

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
    nanosleep(&ts, NULL);
}

/* ---------------- 主流程 ---------------- */

static void *rom_data = NULL;
static size_t rom_size = 0;

static bool core_load(const char *rom_path)
{
    rom_data = read_file(rom_path, &rom_size);
    if (!rom_data) { fprintf(stderr, "cannot read rom: %s\n", rom_path); return false; }
    retro_set_environment(env_cb);
    retro_set_video_refresh(video_cb);
    retro_set_audio_sample(audio_sample_cb);
    retro_set_audio_sample_batch(audio_batch_cb);
    retro_set_input_poll(input_poll_cb);
    retro_set_input_state(input_state_cb);
    retro_init();
    struct retro_game_info info;
    memset(&info, 0, sizeof(info));
    info.path = rom_path;
    info.data = rom_data;
    info.size = rom_size;
    if (!retro_load_game(&info)) { fprintf(stderr, "retro_load_game failed\n"); return false; }
    return true;
}

static int run_selftest(const char *rom_path, long frames)
{
    if (!core_load(rom_path)) return 4;
    struct retro_system_av_info av;
    memset(&av, 0, sizeof(av));
    retro_get_system_av_info(&av);
    printf("E5EMU geometry=%ux%u fps=%.3f\n", av.geometry.base_width, av.geometry.base_height,
           (double)av.timing.fps);
    double target = 1000.0 / ((double)av.timing.fps > 1.0 ? (double)av.timing.fps : 60.0);
    double t_start = now_ms();
    for (long f = 0; f < frames; f++) {
        double t0 = now_ms();
        buttons = ((f / 30) % 2) ? (1u << 3) : 0u;
        retro_run();
        sleep_ms(target - (now_ms() - t0));
    }
    double elapsed = now_ms() - t_start;
    printf("E5EMU frames=%ld elapsed_ms=%.1f fps=%.2f core_frames=%lu\n",
           frames, elapsed, (double)frames * 1000.0 / (elapsed > 0 ? elapsed : 1.0), frame_counter);
    retro_unload_game();
    retro_deinit();
    return 0;
}

static int run_server(const char *rom_path, int port)
{
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    if (ls < 0) { perror("socket"); return 5; }
    int one = 1;
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons((uint16_t)port);
    if (bind(ls, (struct sockaddr *)&addr, sizeof(addr)) < 0) { perror("bind"); close(ls); return 5; }
    if (listen(ls, 1) < 0) { perror("listen"); close(ls); return 5; }
    printf("E5EMU listening 127.0.0.1:%d\n", port);
    fflush(stdout);

    if (!core_load(rom_path)) { close(ls); return 4; }
    struct retro_system_av_info av;
    memset(&av, 0, sizeof(av));
    retro_get_system_av_info(&av);
    printf("E5EMU geometry=%ux%u fps=%.3f\n", av.geometry.base_width, av.geometry.base_height,
           (double)av.timing.fps);
    fflush(stdout);

    const double target = 1000.0 / ((double)av.timing.fps > 1.0 ? (double)av.timing.fps : 60.0);

    for (;;) {
        int cfd = accept(ls, NULL, NULL);
        if (cfd < 0) { if (errno == EINTR) continue; break; }
        setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        if (do_handshake(cfd) != 0) { close(cfd); continue; }
        printf("E5EMU client connected\n");
        fflush(stdout);

        while (1) {
            double t0 = now_ms();
            retro_run();
            if (last_frame && last_w && last_h) {
                size_t need = (size_t)last_w * last_h * 2;
                if (need > frame_copy_cap) {
                    uint8_t *p = realloc(frame_copy, need);
                    if (!p) break;
                    frame_copy = p;
                    frame_copy_cap = need;
                }
                /* 逐行拷贝，兼容 pitch 大于行宽的像素格式 */
                size_t row = (size_t)last_w * 2;
                const uint8_t *src = (const uint8_t *)last_frame;
                for (unsigned y = 0; y < last_h; y++)
                    memcpy(frame_copy + (size_t)y * row, src + (size_t)y * last_pitch, row);
                uint8_t hdr4[4] = { (uint8_t)(last_w & 0xff), (uint8_t)(last_w >> 8),
                                    (uint8_t)(last_h & 0xff), (uint8_t)(last_h >> 8) };
                if (ws_send_frame(cfd, hdr4, frame_copy, need) != 0) break;
            }
            if (ws_read_buttons(cfd) < 0) break;
            sleep_ms(target - (now_ms() - t0));
        }

        printf("E5EMU client disconnected, frames=%lu\n", frame_counter);
        fflush(stdout);
        close(cfd);
        buttons = 0;
    }
    retro_unload_game();
    retro_deinit();
    close(ls);
    return 0;
}

int main(int argc, char **argv)
{
    const char *rom_path = NULL;
    long frames = 600;
    int port = 9510;
    bool selftest = false, serve = false;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--selftest")) selftest = true;
        else if (!strcmp(argv[i], "--serve")) serve = true;
        else if (!rom_path) rom_path = argv[i];
        else { long v = atol(argv[i]); if (v > 100) frames = v; else if (v > 0) port = (int)v; }
    }
    if (!rom_path || (!selftest && !serve)) {
        fprintf(stderr, "usage: e5emu --selftest <rom.nes> [frames]\n"
                        "       e5emu --serve <rom.nes> [port]\n");
        return 2;
    }
    return serve ? run_server(rom_path, port) : run_selftest(rom_path, frames);
}
