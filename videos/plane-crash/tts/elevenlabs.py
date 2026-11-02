"""Narrate the plane video with ElevenLabs and mux it into the final MP4.

Needs ELEVENLABS_API_KEY in the environment. Optional: ELEVENLABS_VOICE_ID
(default: premade voice "Adam"), ELEVENLABS_MODEL (default eleven_multilingual_v2).
Usage: python3 elevenlabs.py
"""
import json, os, subprocess, sys, urllib.request, urllib.error
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
from lines import LINES

KEY = os.environ.get('ELEVENLABS_API_KEY')
if not KEY:
    sys.exit('ELEVENLABS_API_KEY is not set')
VOICE_ID = os.environ.get('ELEVENLABS_VOICE_ID', 'pNInz6obpgDQGcFmaJgB')
MODEL = os.environ.get('ELEVENLABS_MODEL', 'eleven_multilingual_v2')
OUT = os.path.join(D, 'lines_eleven'); os.makedirs(OUT, exist_ok=True)
VIDEO = os.path.join(D, '..', 'plane', 'plane_part1.mp4')
FINAL = os.path.join(D, '..', 'plane', 'plane_part1_elevenlabs.mp4')


def tts(text, path, prev_text, next_text):
    body = {'text': text, 'model_id': MODEL,
            'voice_settings': {'stability': 0.45, 'similarity_boost': 0.8, 'style': 0.35, 'use_speaker_boost': True}}
    if prev_text: body['previous_text'] = prev_text
    if next_text: body['next_text'] = next_text
    req = urllib.request.Request(
        f'https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}?output_format=mp3_44100_128',
        data=json.dumps(body).encode(), method='POST',
        headers={'xi-api-key': KEY, 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(path, 'wb') as f:
            f.write(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f'ElevenLabs error {e.code}: {e.read().decode(errors="replace")[:500]}')


def dur(p):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p]).decode())


inputs, filt = [], []
for i, (st, end, text) in enumerate(LINES):
    raw = os.path.join(OUT, f'raw{i:02d}.mp3')
    if not os.path.exists(raw):
        tts(text, raw, LINES[i - 1][2] if i else None, LINES[i + 1][2] if i + 1 < len(LINES) else None)
    d = dur(raw); slot = end - st - 0.1
    tempo = min(1.35, max(1.0, d / slot))
    print(f'{i:02d} {d:5.2f}s slot {slot:5.2f}s tempo {tempo:.2f}' + ('  !! too long' if d / slot > 1.35 else ''))
    inputs += ['-i', raw]
    filt.append(f'[{i}]atempo={tempo:.3f},adelay={int(st * 1000)}|{int(st * 1000)},apad[v{i}]')
mix = ''.join(f'[v{i}]' for i in range(len(LINES)))
voice = os.path.join(D, 'voice_eleven.wav')
subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex',
                ';'.join(filt) + f';{mix}amix=inputs={len(LINES)}:normalize=0,atrim=0:80[a]',
                '-map', '[a]', '-ar', '44100', '-ac', '2', voice], check=True)
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', VIDEO, '-i', voice, '-filter_complex',
                '[1]asplit[vo][sc];[0:a]volume=0.6[bg];[bg][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=300[duck];'
                '[duck][vo]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]',
                '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '44100',
                '-movflags', '+faststart', FINAL], check=True)
print('done ->', FINAL)
