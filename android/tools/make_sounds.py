"""Benachrichtigungstoene der App - reine Synthese, keine fremden Samples (gleiche Lizenz wie das Repo).

Erzeugt app/src/main/res/raw/snd_*.ogg (braucht ffmpeg mit libvorbis):
    python3 tools/make_sounds.py
"""
import math
import os
import struct
import subprocess
import tempfile
import wave
SR = 44100

def note(f):  # Notenname -> Hz
    names = {"C":-9,"C#":-8,"D":-7,"D#":-6,"E":-5,"F":-4,"F#":-3,"G":-2,"G#":-1,"A":0,"A#":1,"B":2}
    return 440 * 2 ** ((names[f[:-1]] + 12 * (int(f[-1]) - 4)) / 12)

def blank(sec): return [0.0] * int(SR * sec)

def add(buf, start, sig, gain=1.0):
    i0 = int(start * SR)
    need = i0 + len(sig)
    if need > len(buf):
        buf.extend([0.0] * (need - len(buf)))
    for i, v in enumerate(sig):
        buf[i0 + i] += v * gain

def bell(f, dur, bright=1.0, decay=3.0):
    """Glocke/Marimba: Teiltoene mit eigener Abklingzeit, weicher Anschlag."""
    parts = [(1, 1.0, 1.0), (2.0, 0.45 * bright, 1.8), (3.01, 0.22 * bright, 2.6), (4.2, 0.12 * bright, 3.5),
             (5.43, 0.06 * bright, 5)]
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        att = min(1.0, t / 0.004)
        v = sum(a * math.exp(-decay * k * t) * math.sin(2 * math.pi * f * r * t) for r, a, k in parts)
        out.append(att * v)
    return out

def tone(f, dur, shape="sine", decay=0.0, glide=0.0):
    n = int(SR * dur)
    out = []
    ph = 0.0
    for i in range(n):
        t = i / SR
        ff = f * (1 + glide * t / dur)
        ph += 2 * math.pi * ff / SR
        if shape == "sine":
            v = math.sin(ph)
        else:  # weiches Rechteck: ungerade Obertoene
            v = sum(math.sin(k * ph) / k for k in (1, 3, 5, 7)) * 0.8
        env = min(1, t / 0.006) * min(1, (dur - t) / 0.02) * (math.exp(-decay * t) if decay else 1)
        out.append(v * env)
    return out

def reverb(buf, wet=0.22):
    out = buf + [0.0] * int(SR * 0.6)
    for d, g in ((0.029, 0.5), (0.043, 0.4), (0.061, 0.33), (0.089, 0.25), (0.13, 0.18), (0.19, 0.12)):
        k = int(SR * d)
        for i in range(len(buf)):
            out[i + k] += buf[i] * g * wet
    return out

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "res", "raw")


def save(name, buf, peak=0.85):
    """Hall dazu, normieren, als Ogg Vorbis nach res/raw."""
    buf = reverb(buf)
    m = max(abs(v) for v in buf) or 1
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, name + ".wav")
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(b"".join(struct.pack("<h", int(v / m * peak * 32767)) for v in buf))
        os.makedirs(OUT, exist_ok=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-c:a", "libvorbis", "-q:a", "5",
                        os.path.join(OUT, name + ".ogg")], check=True)


# Druck gestartet: zwei Toene aufwaerts (Quinte), Marimba
b = blank(0.1)
add(b, 0.0, bell(note("C5"), 0.6, 0.8, 4))
add(b, 0.14, bell(note("G5"), 0.9, 0.8, 3))
save("snd_start", b)

# Erste Schicht fertig: kurzes helles Doppel-Pling
b = blank(0.1)
add(b, 0.0, bell(note("E6"), 0.35, 1.2, 7), 0.8)
add(b, 0.11, bell(note("B6"), 0.6, 1.2, 5), 0.8)
save("snd_first_layer", b)

# Druck fertig: Fanfare kurz-kurz-lang
b = blank(0.1)
for t, n, d in ((0, "G5", 0.3), (0.13, "G5", 0.3), (0.26, "C6", 1.4)):
    add(b, t, bell(note(n), d, 1.1, 2.5))
add(b, 0.26, bell(note("E6"), 1.4, 0.7, 2.5), 0.5)
save("snd_done", b)

# Alarm: steigende Sirenen-Pulse
b = blank(0.1)
for k in range(4):
    add(b, k * 0.42, tone(note("E5"), 0.32, "square", glide=0.5), 0.6)
save("snd_alarm", b, 0.9)

# Hinweis: leises "Blopp" abwaerts
b = blank(0.1)
add(b, 0.0, tone(note("A5"), 0.22, "sine", decay=9, glide=-0.35))
add(b, 0.12, tone(note("E5"), 0.3, "sine", decay=8, glide=-0.3), 0.7)
save("snd_hint", b, 0.55)
