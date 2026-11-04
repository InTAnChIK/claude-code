const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1320, height: 1980 } });
  const items = [['power', 'powerbank'], ['cup', 'termostakan'], ['buds', 'naushniki']];
  for (const [id, name] of items) for (const m of ['cover', 'detail']) {
    await p.goto('file://' + path.join(__dirname, 'cards.html') + `?p=${id}&m=${m}`);
    await p.evaluate(() => document.fonts.ready);
    const el = await p.$('.page');
    const box = await el.boundingBox();
    const sh = await el.evaluate(e => e.scrollHeight);
    console.log(id, m, Math.round(box.height), 'content', sh);
    await el.screenshot({ path: path.join(__dirname, 'out', `${name}_${m === 'cover' ? '1_oblozhka' : '2_tekst'}.png`) });
  }
  await b.close();
})();
