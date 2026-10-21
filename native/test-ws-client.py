#!/usr/bin/env python3
"""验证 e5emu 的 WebSocket 推帧与按键接收（跑在设备本机，连 127.0.0.1）。

用法：
    python3 native/test-ws-client.py [端口] [帧数]

检查项：
  1. 握手返回 101；
  2. 收到的二进制帧格式为「宽 u16 + 高 u16 + RGB565 像素」，尺寸与核心一致；
  3. 连续收到指定数量的帧（默认 120，约 2 秒 @60fps）；
  4. 发送按键位图（START）后仍然继续出帧（说明输入帧没打断推流）。
"""
import base64
import os
import socket
import struct
import sys
import time


def read_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("connection closed")
        buf += chunk
    return buf


def read_frame(sock: socket.socket) -> bytes:
    head = read_exact(sock, 2)
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read_exact(sock, 8))[0]
    if head[1] & 0x80:
        mask = read_exact(sock, 4)
        payload = bytearray(read_exact(sock, length))
        for i in range(length):
            payload[i] ^= mask[i % 4]
        return bytes(payload)
    return read_exact(sock, length)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9510
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 120

    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        "GET / HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n" % key
    )
    sock.sendall(request.encode())

    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(1024)
    status = response.split(b"\r\n")[0].decode(errors="replace")
    print("handshake:", status)
    if "101" not in status:
        print("FAIL: 握手没有返回 101")
        return 1

    width = height = 0
    t0 = time.monotonic()
    for i in range(frames):
        payload = read_frame(sock)
        if i == 0:
            width, height = struct.unpack("<HH", payload[:4])
            pixels = len(payload) - 4
            print("frame0: %dx%d pixels=%d (expected %d)" % (width, height, pixels, width * height * 2))
            if pixels != width * height * 2:
                print("FAIL: 帧长度与宽高不匹配")
                return 1
    elapsed = time.monotonic() - t0
    print("received %d frames in %.2fs -> %.1f fps" % (frames, elapsed, frames / elapsed if elapsed else 0))

    # 发送 START（libretro 按钮 3）按下
    mask = b"\x01\x02\x03\x04"
    data = struct.pack("<I", 1 << 3)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(b"\x82" + bytes([0x80 | len(masked)]) + mask + masked)
    time.sleep(0.3)

    ok = 0
    for _ in range(10):
        read_frame(sock)
        ok += 1
    print("frames after input: %d -> %s" % (ok, "OK" if ok == 10 else "FAIL"))
    sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
