// usage: node render.js preview t1,t2,...  |  node render.js video out.mp4 audio.wav
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

(async () => {
  const [mode, a1, a2] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  page.on('pageerror', e => console.error('PAGE ERROR', e.message));
  await page.goto('file://' + path.join(__dirname, 'anim.html'));
  await page.evaluate(() => window.ready);
  const grab = async (t, q) => {
    const url = await page.evaluate(([t, q]) => { window.render(t); return document.getElementById('c').toDataURL('image/jpeg', q); }, [t, q]);
    return Buffer.from(url.split(',')[1], 'base64');
  };
  if (mode === 'preview') {
    fs.mkdirSync(path.join(__dirname, 'preview'), { recursive: true });
    for (const t of a1.split(',').map(Number)) fs.writeFileSync(path.join(__dirname, 'preview', `t${String(t).padStart(5, '0')}.jpg`), await grab(t, 0.85));
  } else {
    const FPS = 30, N = 80 * FPS;
    const ff = spawn('ffmpeg', ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-', '-i', a2,
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', a1], { stdio: ['pipe', 'inherit', 'inherit'] });
    for (let i = 0; i < N; i++) {
      const buf = await grab(i / FPS, 0.93);
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      if (i % 300 === 0) console.log('frame', i, '/', N);
    }
    ff.stdin.end();
    await new Promise(r => ff.on('close', r));
  }
  await browser.close();
})();
