"""Draws the shared arena from above and pushes it to a Telegram channel live stream (RTMP) with ffmpeg.

server.py starts this as a child process and writes the game state to its stdin, one JSON line at a time:
  {"p": [[id, name, skin, x, z, m, human], ...], "n": <real players>, "top": [[name, best], ...]}   (10x a second)
  {"f": [[x, z, big, colour], ...]}                                                                (once a second)
Environment: STREAM_URL (rtmps://.../s/ + key, or a file path for testing), STREAM_FPS (default 15).
"""
import json, math, os, subprocess, sys, threading, time
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
FPS = int(os.environ.get("STREAM_FPS", "15"))
URL = os.environ.get("STREAM_URL", "")
S = float(os.environ.get("ARENA_S", "130"))
AX, AY, AS = 40, 40, 640                     # arena square on screen
K = AS / (2 * S)                              # pixels per world unit
FOOD_COLORS = [(255, 77, 94), (63, 123, 255), (47, 208, 106), (255, 210, 31), (176, 92, 255), (255, 138, 31), (31, 208, 208), (255, 92, 200)]
SKIN_COLORS = {"yashil": (47, 208, 106), "tarvuz": (60, 201, 90), "konfet": (255, 90, 120), "leopard": (255, 190, 80),
               "gulli": (150, 230, 175), "kamalak": (255, 170, 60), "muz": (120, 200, 245), "olov": (255, 110, 30),
               "lava": (150, 40, 15), "chaqmoq": (40, 70, 200), "galaktika": (60, 30, 140), "oltin": (230, 175, 20)}


def font(size, bold=True):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/opentype/inter/Inter-Bold.otf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


F_TITLE, F_BIG, F_MID, F_SM, F_XS = font(34), font(24), font(19), font(16), font(13)
state = {"p": [], "n": 0, "top": [], "f": []}
lock = threading.Lock()


def reader():
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        with lock:
            state.update(m)
    os._exit(0)                                  # the game server went away


def scr(x, z):
    return AX + (x + S) * K, AY + (z + S) * K


def make_background():
    bg = Image.new("RGB", (W, H), (12, 20, 60))
    d = ImageDraw.Draw(bg)
    for y in range(H):                           # soft vertical gradient
        c = int(12 + 18 * y / H)
        d.line([(0, y), (W, y)], fill=(c, c + 10, 60 + c))
    d.rounded_rectangle([AX - 10, AY - 10, AX + AS + 10, AY + AS + 10], radius=18, fill=(70, 120, 220))
    tile = 10
    n = int(2 * S / tile)
    for i in range(n):
        for j in range(n):
            x0, y0 = AX + i * tile * K, AY + j * tile * K
            d.rectangle([x0, y0, x0 + tile * K, y0 + tile * K], fill=(143, 224, 74) if (i + j) % 2 else (124, 207, 58))
    d.rounded_rectangle([720, 40, 1240, 680], radius=22, fill=(20, 32, 90))
    return bg


def shade(c, f):
    return tuple(int(v + (255 - v) * f) if f > 0 else int(v * (1 + f)) for v in c)


def fmt(n):
    n = int(n)
    return (f"{n / 1000:.0f}K" if n >= 10000 else f"{n / 1000:.1f}K") if n >= 1000 else str(n)


def color_of(skin):
    if isinstance(skin, str) and skin.startswith("#") and len(skin) == 7:
        return tuple(int(skin[i:i + 2], 16) for i in (1, 3, 5))
    return SKIN_COLORS.get(skin, (47, 208, 106))


def draw_frame(bg, players, food, n_real, top, t):
    img = bg.copy()
    d = ImageDraw.Draw(img)
    for x, z, big, c in food:
        sx, sy = scr(x, z)
        r = 2.6 if big else 1.6
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=FOOD_COLORS[c % 8])
    for p in sorted(players, key=lambda p: p["m"]):
        sx, sy = scr(p["x"], p["z"])
        r = max(3.0, 0.45 * math.sqrt(p["m"]) * K)
        col = color_of(p["skin"])
        d.ellipse([sx - r + 2, sy - r + 4, sx + r + 2, sy + r + 4], fill=(40, 90, 30))          # shadow
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=shade(col, -0.25))
        d.ellipse([sx - r * 0.88, sy - r * 0.9, sx + r * 0.82, sy + r * 0.8], fill=col)
        if r > 7:
            d.ellipse([sx - r * 0.55, sy - r * 0.62, sx - r * 0.1, sy - r * 0.25], fill=shade(col, 0.45))
        if p["skin"] == "galaktika" and r > 10:
            for k in range(7):
                a = k * 2.4
                d.ellipse([sx + math.cos(a) * r * 0.55 - 1, sy + math.sin(a) * r * 0.5 - 1, sx + math.cos(a) * r * 0.55 + 1, sy + math.sin(a) * r * 0.5 + 1], fill=(255, 255, 255))
        if r > 9:
            label = p["name"][:12]
            f = F_SM if r > 22 else F_XS
            d.text((sx, sy - r - 4), f"{label} {fmt(p['m'] * 10)}", font=f, fill=(255, 255, 255), anchor="ms",
                   stroke_width=3, stroke_fill=(20, 30, 10))
    # right panel
    blink = int(t * 2) % 2 == 0
    d.ellipse([748, 66, 768, 86], fill=(255, 40, 60) if blink else (150, 20, 35))
    d.text((780, 58), "JONLI", font=F_BIG, fill=(255, 90, 100))
    d.text((748, 96), "SHAR YUTAR", font=F_TITLE, fill=(255, 225, 77))
    d.text((748, 142), f"Hozir maydonda: {n_real} o'yinchi", font=F_MID, fill=(200, 215, 255))
    d.text((748, 182), "MAYDONDAGI TOP-10", font=F_SM, fill=(150, 170, 230))
    ranked = sorted(players, key=lambda p: -p["m"])[:10]
    y = 208
    for i, p in enumerate(ranked, 1):
        col = (255, 225, 77) if i <= 3 else (255, 255, 255)
        d.text((748, y), f"{i:>2}. {p['name'][:16]}", font=F_MID, fill=col)
        d.text((1212, y), fmt(p["m"] * 10), font=F_MID, fill=col, anchor="ra")
        y += 27
    y += 10
    d.text((748, y), "REKORDLAR", font=F_SM, fill=(150, 170, 230))
    y += 26
    for i, (name, best) in enumerate(top[:5], 1):
        d.text((748, y), f"{i}. {str(name)[:16]}", font=F_SM, fill=(220, 230, 255))
        d.text((1212, y), fmt(best), font=F_SM, fill=(220, 230, 255), anchor="ra")
        y += 23
    d.rounded_rectangle([748, 618, 1212, 660], radius=14, fill=(40, 180, 75))
    d.text((980, 639), "O'ynash: @VIIZUAL_BOT", font=F_MID, fill=(255, 255, 255), anchor="mm")
    return img


def ffmpeg():
    out = URL if URL else "/tmp/stream_test.flv"
    cmd = ["ffmpeg", "-loglevel", "warning", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-b:v", "700k", "-maxrate", "900k", "-bufsize", "1800k",
           "-g", str(FPS * 2), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "48k", "-shortest", "-f", "flv", out]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def main():
    threading.Thread(target=reader, daemon=True).start()
    bg = make_background()
    smooth = {}
    limit = float(os.environ.get("STREAM_SECONDS", "0"))   # for tests: stop after N seconds
    start = time.time()
    while True:
        proc = ffmpeg()
        nxt = time.time()
        try:
            while proc.poll() is None:
                with lock:
                    raw, food, n_real, top = state["p"], state["f"], state["n"], state["top"]
                players = []
                seen = set()
                for pid, name, skin, x, z, m, human in raw:
                    seen.add(pid)
                    sp = smooth.get(pid)
                    if not sp or abs(sp[0] - x) + abs(sp[1] - z) > 20:
                        sp = smooth[pid] = [x, z]
                    sp[0] += (x - sp[0]) * 0.35
                    sp[1] += (z - sp[1]) * 0.35
                    players.append({"name": name, "skin": skin, "x": sp[0], "z": sp[1], "m": m})
                for pid in list(smooth):
                    if pid not in seen:
                        del smooth[pid]
                frame = draw_frame(bg, players, food, n_real, top, time.time())
                proc.stdin.write(frame.tobytes())
                if limit and time.time() - start > limit:
                    proc.stdin.close()
                    proc.wait()
                    return
                nxt += 1 / FPS
                time.sleep(max(0, nxt - time.time()))
                if time.time() - nxt > 2:              # fell behind: resync instead of bursting
                    nxt = time.time()
        except (BrokenPipeError, OSError):
            pass
        try:
            proc.kill()
        except Exception:
            pass
        time.sleep(5)                                   # Telegram dropped the stream: reconnect


if __name__ == "__main__":
    main()
