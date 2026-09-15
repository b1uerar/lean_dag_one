// Optional image export. Install @viz-js/viz and playwright, or set their module paths.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {instance} = require(process.env.VIZ_MODULE || '@viz-js/viz');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const output = process.argv[2] ? path.resolve(process.argv[2]) :
    path.resolve(__dirname, '../../output/lcm_assoc_local');
  const graph = JSON.parse(fs.readFileSync(path.join(output, 'graph.json'), 'utf8'));
  const viz = await instance();
  const browser = await chromium.launch({headless: true});
  try {
    {
      assert.equal(graph.scope, 'input_file');
      const nodes = graph.nodes;
      const edges = graph.edges;
      const title = `${graph.root}\nTheorems in ${path.basename(graph.input_file)}`;
      const subtitle = `${nodes.length} nodes / ${edges.length} edges | ${graph.summary.contains_sorry} sorry | Imports excluded`;
      const model = {
        directed: true,
        graphAttributes: {rankdir: 'LR', bgcolor: '#ffffff', pad: '0.35',
          nodesep: '0.3', ranksep: '0.7',
          label: title + '\n' + subtitle, labelloc: 't', fontsize: '18', fontname: 'sans-serif'},
        nodeAttributes: {shape: 'box', style: 'rounded,filled', fontname: 'sans-serif', fontsize: '14', margin: '0.22,0.1'},
        edgeAttributes: {color: '#94a3a0', arrowsize: '0.65', penwidth: '1'},
        nodes: nodes.map(n => ({name: n.id, attributes: {
          label: n.name, tooltip: n.statement,
          fillcolor: n.id === graph.root ? '#dcfce7' : n.kind === 'axiom' ? '#f4f4f5' : '#f0fdfa',
          color: n.kind === 'axiom' ? '#71717a' : '#0f766e',
          penwidth: n.id === graph.root ? '3' : '1',
        }})),
        edges: edges.map(e => ({tail: e.source, head: e.target, attributes: {
          style: e.kinds.length === 1 && e.kinds[0] === 'statement' ? 'dashed' : 'solid',
        }})),
      };
      const prefix = 'full';
      const svg = viz.renderString(model, {format: 'svg', engine: 'dot'});
      const svgPath = path.join(output, `${prefix}.svg`);
      fs.writeFileSync(svgPath, svg);
      const page = await browser.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(pathToFileURL(svgPath).href);
      const dimensions = await page.locator('svg').evaluate(svg => {
        const vb = svg.viewBox.baseVal;
        const scale = Math.min(1.4, 3000 / vb.width, 5000 / vb.height);
        const width = Math.ceil(vb.width * scale), height = Math.ceil(vb.height * scale);
        svg.setAttribute('width', width); svg.setAttribute('height', height);
        svg.style.display = 'block';
        return {width, height};
      });
      await page.setViewportSize(dimensions);
      const pngPath = path.join(output, `${prefix}.png`);
      await page.screenshot({path: pngPath});
      assert.equal(await page.locator('g.node').count(), nodes.length);
      assert.equal(await page.locator('g.edge').count(), edges.length);
      assert.deepEqual(errors, []);
      console.log(`${prefix}: ${nodes.length} nodes, ${edges.length} edges; ${dimensions.width}x${dimensions.height}; ${pngPath}`);
      await page.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
