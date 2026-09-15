// Optional browser check: PLAYWRIGHT_MODULE=/path/to/playwright node tests/check_viewer.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const output = path.resolve(__dirname, '../output/demo');
  const graph = JSON.parse(fs.readFileSync(path.join(output, 'graph.json'), 'utf8'));
  const browser = await chromium.launch({headless: true});
  try {
    for (const viewport of [{width: 1440, height: 900}, {width: 390, height: 844}]) {
      const page = await browser.newPage({viewport});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(pathToFileURL(path.join(output, 'graph.html')).href);
      assert.equal(await page.locator('.node').count(), graph.nodes.length);
      assert.equal(await page.locator('#node-name').textContent(), graph.root);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.locator('#node-status').textContent(), 'Depends on sorry');
      await page.locator('#sorry-paths').check();
      assert.equal(await page.locator('.node:not(.muted)').count(), 3);
      await page.locator('#sorry-paths').uncheck();
      await page.locator('#search').fill('Demo.unfinished');
      assert.equal(await page.locator('.node:not(.muted)').count(), 1);
      await page.locator('#search').fill('');
      await page.locator('.node[data-id="Demo.unfinished"]').click();
      assert.equal(await page.locator('#node-status').textContent(), 'Contains sorry');
      assert.equal(await page.locator('#proof-sorry').textContent(), 'Yes');
      await page.locator('#zoom').fill('100');
      const svgWidth = await page.locator('#viewport svg').evaluate(el => el.getBoundingClientRect().width);
      assert(svgWidth > 500);
      await page.locator('#zoom').fill('80');
      const downloadPromise = page.waitForEvent('download');
      await page.locator('#export-json').click();
      const download = await downloadPromise;
      const downloaded = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
      assert.equal(downloaded.root, graph.root);
      await page.screenshot({path: path.join(output, `viewer-${viewport.width}.png`), fullPage: true});
      assert.deepEqual(errors, []);
      console.log(`Viewer ${viewport.width}x${viewport.height}: rendering, selection, filtering, zoom, download passed`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
