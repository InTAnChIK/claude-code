# «Самолёт падает. У вас 90 секунд» — часть 1

Вертикальный ролик 1080×1920, 80 секунд.

| Файл | Что это |
|---|---|
| `plane/plane_part1.mp4` | Видео с фоновым звуком, без голоса |
| `plane/plane_part1_ozvuchka.mp4` | Видео с озвучкой Piper (голос `dmitri`) |
| `plane/anim.html` | Анимация (canvas), функция `render(t)` |
| `plane/render.js` | Рендер в MP4 через Playwright + ffmpeg |
| `plane/make_audio.sh` | Синтез фонового звука `audio.wav` |
| `tts/lines.py` | Текст озвучки и тайминги реплик |
| `tts/voice.py` | Озвучка через Piper (офлайн) |
| `tts/elevenlabs.py` | Озвучка через ElevenLabs API |

## Озвучка ElevenLabs

Нужна переменная окружения `ELEVENLABS_API_KEY`. По желанию: `ELEVENLABS_VOICE_ID`
(по умолчанию голос Adam) и `ELEVENLABS_MODEL` (по умолчанию `eleven_multilingual_v2`).

```bash
python3 videos/plane-crash/tts/elevenlabs.py
```

Результат: `plane/plane_part1_elevenlabs.mp4`.

## Пересобрать видео

```bash
cd videos/plane-crash/plane && ./make_audio.sh && node render.js video plane_part1.mp4 audio.wav
```
