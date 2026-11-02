import json, subprocess, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
D = os.path.dirname(os.path.abspath(__file__))
VOICE = sys.argv[1] if len(sys.argv) > 1 else 'dmitri'
OUT = os.path.join(D, 'lines_' + VOICE); os.makedirs(OUT, exist_ok=True)
# (start, slot_end, text)
from lines import LINES
model = os.path.join(D, 'voices', f'ru_RU-{VOICE}-medium.onnx')
def dur(p):
    return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p]).decode())
inputs, filt = [], []
for i, (st, end, text) in enumerate(LINES):
    raw = os.path.join(OUT, f'raw{i:02d}.wav')
    subprocess.run([os.path.join(D, 'venv/bin/piper'), '-m', model, '-f', raw, '--length-scale', '0.92', '--sentence-silence', '0.25'],
                   input=text.encode(), check=True, capture_output=True)
    d = dur(raw); slot = end - st - 0.1
    tempo = max(1.0, d / slot)
    print(f'{i:02d} {d:5.2f}s slot {slot:5.2f}s tempo {tempo:.2f}' + ('  !!' if tempo > 1.3 else ''))
    inputs += ['-i', raw]
    filt.append(f'[{i}]atempo={tempo:.3f},adelay={int(st*1000)}|{int(st*1000)},apad[v{i}]')
mix = ''.join(f'[v{i}]' for i in range(len(LINES)))
fc = ';'.join(filt) + f';{mix}amix=inputs={len(LINES)}:normalize=0,atrim=0:80,' \
     'highpass=f=80,acompressor=threshold=0.1:ratio=3:attack=5:release=120,volume=1.6[a]'
subprocess.run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', fc, '-map', '[a]', '-ar', '44100', '-ac', '2',
                os.path.join(D, f'voice_{VOICE}.wav')], check=True)
print('ok')
