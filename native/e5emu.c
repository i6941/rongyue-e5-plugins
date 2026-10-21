/* e5emu — E5 上的原生 libretro 前端（第一阶段：自检模式）
 *
 * 目的：把 fceumm 核心静态链接进来，在设备上直接跑 ROM，
 * 输出帧率与帧校验，用来证明"原生路线在这台机器上能不能满帧"。
 * 网络推流（WebSocket）留到第二阶段；这一阶段不监听任何端口。
 *
 * 编译（在电脑上交叉编译，目标 aarch64 musl）：
 *   zig cc -target aarch64-linux-musl -O2 -static e5emu.c <core sources> -o e5emu
 *
 * 用法：
 *   ./e5emu --selftest /path/to/rom.nes [帧数]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>

#include "libretro.h"

static unsigned buttons = 0;          /* 位图：第 n 位 = libretro 按钮 n 是否按下 */
static const void *last_frame = NULL;
static unsigned last_w = 0, last_h = 0;
static size_t last_pitch = 0;
static unsigned long frame_counter = 0;
static enum retro_pixel_format pixfmt = RETRO_PIXEL_FORMAT_0RGB1555;

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
    struct timespec ts;
    ts.tv_sec = (time_t)(ms / 1000.0);
    ts.tv_nsec = (long)((ms - (double)ts.tv_sec * 1000.0) * 1e6);
    nanosleep(&ts, NULL);
}

int main(int argc, char **argv)
{
    const char *rom_path = NULL;
    long frames = 600;
    bool selftest = false;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--selftest")) selftest = true;
        else if (!rom_path) rom_path = argv[i];
        else frames = atol(argv[i]);
    }
    if (!selftest || !rom_path || frames <= 0) {
        fprintf(stderr, "usage: e5emu --selftest <rom.nes> [frames]\n");
        return 2;
    }

    size_t rom_size = 0;
    void *rom_data = read_file(rom_path, &rom_size);
    if (!rom_data) {
        fprintf(stderr, "cannot read rom: %s\n", rom_path);
        return 3;
    }

    retro_set_environment(env_cb);
    retro_set_video_refresh(video_cb);
    retro_set_audio_sample(audio_sample_cb);
    retro_set_audio_sample_batch(audio_batch_cb);
    retro_set_input_poll(input_poll_cb);
    retro_set_input_state(input_state_cb);
    retro_init();

    struct retro_system_info sys;
    memset(&sys, 0, sizeof(sys));
    retro_get_system_info(&sys);

    struct retro_game_info info;
    memset(&info, 0, sizeof(info));
    info.path = rom_path;
    info.data = rom_data;
    info.size = rom_size;
    info.meta = NULL;

    if (!retro_load_game(&info)) {
        fprintf(stderr, "retro_load_game failed\n");
        retro_deinit();
        free(rom_data);
        return 4;
    }

    struct retro_system_av_info av;
    memset(&av, 0, sizeof(av));
    retro_get_system_av_info(&av);

    printf("E5EMU core=%s version=%s\n", sys.library_name ? sys.library_name : "?",
           sys.library_version ? sys.library_version : "?");
    printf("E5EMU geometry=%ux%u fps=%.3f sample_rate=%.0f pixfmt=%d\n",
           av.geometry.base_width, av.geometry.base_height,
           (double)av.timing.fps, (double)av.timing.sample_rate, (int)pixfmt);
    printf("E5EMU rom=%s bytes=%zu\n", rom_path, rom_size);
    fflush(stdout);

    const double target_ms = 1000.0 / ((double)av.timing.fps > 1.0 ? (double)av.timing.fps : 60.0);
    double t_start = now_ms();
    for (long f = 0; f < frames; f++) {
        double t0 = now_ms();
        /* 每 30 帧按一次 START（按钮 3），验证输入路径 */
        buttons = ((f / 30) % 2) ? (1u << 3) : 0u;
        retro_run();
        double spent = now_ms() - t0;
        if (spent < target_ms) sleep_ms(target_ms - spent);
    }
    double elapsed = now_ms() - t_start;

    unsigned long sum = 0;
    if (last_frame) {
        const unsigned char *p = (const unsigned char *)last_frame;
        size_t bytes = (size_t)last_h * last_pitch;
        for (size_t i = 0; i < bytes; i += 4096) sum += p[i];
    }

    printf("E5EMU frames=%ld elapsed_ms=%.1f fps=%.2f core_frames=%lu size=%ux%u checksum=%lu\n",
           frames, elapsed, (double)frames * 1000.0 / (elapsed > 0 ? elapsed : 1.0),
           frame_counter, last_w, last_h, sum);
    fflush(stdout);

    retro_unload_game();
    retro_deinit();
    free(rom_data);
    return (frame_counter > 0 && last_w > 0) ? 0 : 5;
}
