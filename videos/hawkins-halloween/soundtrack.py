"""Compose an original instrumental bed and mix the acquired bundled action cues."""
from pathlib import Path
import json
import subprocess
import wave
import numpy as np

ROOT = Path(__file__).resolve().parent
RATE, SECONDS = 48000, 40
audio = np.zeros((RATE * SECONDS, 2), dtype=np.float64)

def tone(start, length, hz, gain, pan=0, bright=False):
    n = min(int(length * RATE), len(audio) - int(start * RATE))
    if n <= 0:
        return
    t = np.arange(n) / RATE
    attack = np.minimum(t / .018, 1)
    release = np.minimum((length - t) / .18, 1)
    env = attack * np.maximum(release, 0) * np.exp(-t * (2.8 if bright else .35))
    signal = np.sin(2 * np.pi * hz * t)
    for harmonic, weight in [(2, .25), (3, .11), (5, .04)]:
        signal += weight * np.sin(2 * np.pi * hz * harmonic * t)
    signal *= env * gain
    at = int(start * RATE)
    audio[at:at+n, 0] += signal * np.sqrt((1-pan)/2)
    audio[at:at+n, 1] += signal * np.sqrt((1+pan)/2)

def effect(name, start, gain):
    data = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(ROOT/'assets'/'sfx'/f'{name}.mp3'), '-f', 'f32le', '-ar', str(RATE), '-ac', '2', '-'])
    sample = np.frombuffer(data, dtype='<f4').reshape(-1, 2)
    at = int(start*RATE)
    n = min(len(sample), len(audio)-at)
    audio[at:at+n] += sample[:n]*gain

# A minor with an original five-note asymmetric phrase; no source-song samples.
beat = 60/90
roots = [55, 65.4064, 73.4162, 61.7354]
phrase = [0, 7, 12, 3, 10, 7, 15, 12, 0, 10]
for bar in range(15):
    at = bar * beat * 4
    root = roots[(bar//2) % 4]
    tension = .38 if 14 <= at < 22 else 1
    tone(at, beat*4+.3, root, .078*tension)
    tone(at, beat*4+.3, root*1.005, .025*tension, -.55)
    for i in range(8):
        start = at+i*beat/2
        if start >= 38:
            continue
        semitone = phrase[(bar*8+i) % len(phrase)]
        gain = (.033 if start < 6 else .055)*(.3 if 14 <= start < 22 else 1)
        tone(start, .5, root*4*2**(semitone/12), gain, (-.45,.4)[i%2], True)
        if start+beat*.75 < 39:
            tone(start+beat*.75, .5, root*4*2**(semitone/12), gain*.25, (.6,-.6)[i%2], True)

for t in [.14,.34,.58,3.28,3.64,7.0,8.1,22.7,23.8,27.0,31.0,34.15,34.42]:
    effect('click', t, .22 if t<1 else .13)
for t in [10.2,14.1,26.0,37.15]:
    effect('impact',t,.25)
for t in [6.08,9.95,18.08,25.85,29.95,36.98]:
    effect('whoosh',t,.11)

fade = np.minimum(np.arange(len(audio))/RATE/.2, 1) * np.minimum((SECONDS-np.arange(len(audio))/RATE)/1.1, 1)
audio *= fade[:, None]
peak = float(np.max(np.abs(audio)))
audio *= .82/max(peak,1e-9)
out = ROOT/'assets'/'soundtrack.wav'
with wave.open(str(out), 'wb') as f:
    f.setnchannels(2); f.setsampwidth(2); f.setframerate(RATE)
    f.writeframes((audio*32767).astype('<i2').tobytes())
(ROOT/'audio_meta.json').write_text(json.dumps({'duration_s': SECONDS, 'sample_rate': RATE, 'bpm':90, 'voiceover':False, 'score':'Original procedural instrumental, A minor, 90 BPM', 'sfx_source':'HyperFrames bundled.sfx; acquired using media-use resolve', 'peak_dbfs':20*np.log10(np.max(np.abs(audio)))},indent=2),encoding='utf-8')
print(out)
