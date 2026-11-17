'use strict';
const { chromium } = require('/home/lakshaya/projects/Recordly/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const HTML = 'file:///home/lakshaya/projects/hermes-klieg/docs/explainer/index.html';
const WORK = '/tmp/klieg-explainer';
const TOTAL_MS = 50800;

(async () => {
  fs.mkdirSync(WORK, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: WORK, size: { width: 1920, height: 1080 } },
  });
  const page = await ctx.newPage();
  await page.goto(HTML, { waitUntil: 'load' });
  await page.waitForTimeout(TOTAL_MS);
  const video = page.video();
  await ctx.close();
  await browser.close();
  if (!video) {
    console.error('no video');
    process.exit(1);
  }
  const src = await video.path();
  const dest = path.join(WORK, 'raw.webm');
  fs.copyFileSync(src, dest);
  console.log('raw', dest, fs.statSync(dest).size);
})();
