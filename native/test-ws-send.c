#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <sys/uio.h>
#include <assert.h>

static uint8_t *g_out = NULL;
static size_t g_out_len = 0;
static size_t g_step = 4096;

static ssize_t mock_writev(int fd, const struct iovec *iov, int iovcnt)
{
    (void)fd;
    size_t rem = g_step;
    size_t written = 0;
    for (int i = 0; i < iovcnt; i++) {
        if (rem == 0) break;
        size_t take = iov[i].iov_len < rem ? iov[i].iov_len : rem;
        memcpy(g_out + g_out_len, iov[i].iov_base, take);
        g_out_len += take;
        written += take;
        rem -= take;
    }
    return (ssize_t)written;
}

#define writev mock_writev

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
    int iovcnt = 3;
    size_t want = hlen + hdr_len + bytes;
    size_t done = 0;
    while (done < want) {
        ssize_t r = writev(fd, iov, iovcnt);
        if (r <= 0) return -1;
        done += (size_t)r;
        if (done >= want) break;
        size_t skip = done;
        const uint8_t *base[3] = { head, hdr, pixels };
        size_t orig_len[3] = { hlen, hdr_len, bytes };
        int k = 0;
        for (int i = 0; i < 3; i++) {
            if (skip >= orig_len[i]) {
                skip -= orig_len[i];
            } else {
                iov[k].iov_base = (void *)(base[i] + skip);
                iov[k].iov_len = orig_len[i] - skip;
                skip = 0;
                k++;
            }
        }
        iovcnt = k;
        if (iovcnt == 0) break;
    }
    return 0;
}

int main(void)
{
    g_out = (uint8_t *)malloc(300000);
    uint8_t hdr[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    size_t psize = 195840; /* 高清电影单帧尺寸 */
    uint8_t *pixels = (uint8_t *)malloc(psize);
    for (size_t i = 0; i < psize; i++) pixels[i] = (uint8_t)(i & 0xff);

    size_t steps[] = { 1, 7, 128, 4096, 16384, 65536 };
    for (size_t s = 0; s < sizeof(steps)/sizeof(steps[0]); s++) {
        g_step = steps[s];
        g_out_len = 0;
        int rc = ws_send_frame(1, hdr, 8, pixels, psize);
        assert(rc == 0);
        assert(g_out_len == 10 + 8 + psize);
        assert(g_out[0] == 0x82 && g_out[1] == 127);
        assert(memcmp(g_out + 10, hdr, 8) == 0);
        assert(memcmp(g_out + 18, pixels, psize) == 0);
    }
    printf("ALL_HIGH_RES_C_TESTS_PASSED\n");
    free(pixels);
    free(g_out);
    return 0;
}
