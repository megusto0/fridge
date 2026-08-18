/**
 * Automated Test Suite for Fridge Web UI Logic
 * Tests all buttons, transitions, calculations, and paths in DCLogic.
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

// 1. Extract DCLogic from web_ui/Холодильник.dc.html
const htmlPath = path.resolve(__dirname, '../web_ui/Холодильник.dc.html');
const htmlContent = fs.readFileSync(htmlPath, 'utf8');
const scriptMatch = htmlContent.match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/);
assert(scriptMatch, 'Could not find <script type="text/x-dc"> in Холодильник.dc.html');

// Create mock environment
global.window = {
  location: { protocol: 'http:' },
  innerWidth: 1024,
  innerHeight: 768
};
global.localStorage = {
  store: {},
  getItem(k) { return this.store[k] || null; },
  setItem(k, v) { this.store[k] = String(v); },
  removeItem(k) { delete this.store[k]; },
  clear() { this.store = {}; }
};
global.fetch = async (url, options = {}) => {
  return {
    ok: true,
    status: 200,
    json: async () => {
      if (url.includes('/suggest-name')) return { name: 'Индейка с овощами', source: 'fast' };
      if (url.includes('/portions') || url.includes('/finalize')) return { status: 'ready' };
      if (url.includes('/consume')) return { status: 'consumed' };
      if (url.includes('/inventory')) return [];
      if (url.includes('/batches')) return [];
      return { id: 'mock-id-' + Date.now(), name: 'Партия' };
    }
  };
};

class MockDCLogic {
  setState(patch, cb) {
    this.state = Object.assign({}, this.state, patch);
    if (typeof cb === 'function') cb();
  }
}

// Evaluate Component class definition extending DCLogic
const contextFunc = new Function('DCLogic', `${scriptMatch[1]}; return Component;`);
const DCLogic = contextFunc(MockDCLogic);

console.log('🧪 Starting Web UI Logic Automated Tests...\n');
let passedTests = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passedTests++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(err);
    process.exit(1);
  }
}

// Test 1: Initialization & Default State
test('1. Default initialization and state setup', () => {
  const ui = new DCLogic();
  assert.strictEqual(ui.state.route, 'fridge');
  assert.strictEqual(ui.state.chip, 'Все');
  assert.deepStrictEqual(ui.state.sel, {});
  assert.strictEqual(ui.state.prepChip, 'Все');
});

// Test 2: Product Selection - 1-Click Toggle
test('2. Product 1-click select and deselect', () => {
  const ui = new DCLogic();
  const testProd = ui.cat[0];
  
  // Select
  ui.toggleSel(testProd.id);
  assert.strictEqual(ui.state.sel[testProd.id], testProd.avail);
  assert.strictEqual(ui.selList().length, 1);
  
  // Deselect
  ui.toggleSel(testProd.id);
  assert.strictEqual(ui.state.sel[testProd.id], undefined);
  assert.strictEqual(ui.selList().length, 0);
});

// Test 3: Product Amount Sheet (Mealprep Mode vs Direct Consume Mode)
test('3. Amount Sheet - Mealprep mode vs Consume mode', () => {
  const ui = new DCLogic();
  const testProd = ui.cat[0]; // e.g. 500g product
  
  // Open in Mealprep mode
  ui.openAmount(testProd.id, 'prep');
  assert.strictEqual(ui.state.sheet.kind, 'amount');
  assert.strictEqual(ui.state.sheet.mode, 'prep');
  
  let vals = ui.renderVals();
  assert.strictEqual(vals.isAmountSheet, true);
  assert.strictEqual(vals.sheetFieldLabel, 'В милпреп:');
  
  // Set custom amount
  ui.setAmount(testProd.id, 250);
  assert.strictEqual(ui.state.sel[testProd.id], 250);
  assert.strictEqual(ui.state.sheet, null);
  
  // Open in Consume mode
  ui.openAmount(testProd.id, 'consume');
  assert.strictEqual(ui.state.sheet.mode, 'consume');
  vals = ui.renderVals();
  assert.strictEqual(vals.sheetFieldLabel, 'Съедено:');
  assert(vals.sheetTitle.includes('Сколько съедено'));
});

// Test 4: Direct Consumption (Full & Partial)
test('4. Direct Consumption updates stock correctly', async () => {
  const ui = new DCLogic();
  const testProd = ui.cat[0];
  const initialAvail = ui.avail(testProd);
  
  // Partial consume 150g
  await ui.consumeLots([{ lot_id: testProd.id, quantity: 150, unit: 'g' }], 'consumed');
  assert.strictEqual(ui.state.stock[testProd.id], initialAvail - 150);
  
  // Full consume remaining
  const remaining = ui.avail(testProd);
  await ui.consumeLots([{ lot_id: testProd.id, quantity: remaining, unit: 'g' }], 'consumed');
  assert.strictEqual(ui.state.stock[testProd.id], 0);
});

// Test 5: Composer Wizard Navigation (Step 1 -> 2 -> 3 -> 4)
test('5. Composer Wizard steps and calculations', async () => {
  const ui = new DCLogic();
  const p1 = ui.cat[0];
  const p2 = ui.cat[1];
  ui.setAmount(p1.id, 300);
  ui.setAmount(p2.id, 200);
  
  // Start Composer
  await ui.startComposer();
  assert.strictEqual(ui.state.route, 'composer');
  assert.strictEqual(ui.state.comp.step, 1);
  
  // Step 1 -> 2
  ui.step(2);
  assert.strictEqual(ui.state.comp.step, 2);
  
  // Step 2: Custom Name Setting
  ui.setState({ comp: Object.assign({}, ui.state.comp, { name: 'Мой фирменный обед' }) });
  assert.strictEqual(ui.dishName(), 'Мой фирменный обед');
  
  // Step 2 -> 3 (Portioning)
  ui.step(3);
  assert.strictEqual(ui.state.comp.step, 3);
  
  // Equal portions mode (3 containers)
  ui.setState({ comp: Object.assign({}, ui.state.comp, { mode: 'equal', count: 3 }) });
  const wEqual = ui.weights();
  assert.strictEqual(wEqual.length, 3);
  
  // Fixed weight mode (200g)
  ui.setState({ comp: Object.assign({}, ui.state.comp, { mode: 'fixed', fixed: 200, keepRem: true }) });
  const wFixed = ui.weights();
  assert(wFixed.length >= 2);
  
  // Custom manual mode
  ui.setState({ comp: Object.assign({}, ui.state.comp, { mode: 'custom', rows: [250, 150] }) });
  const wCustom = ui.weights();
  assert.deepStrictEqual(wCustom, [250, 150]);
  
  // Step 3 -> 4 (Review)
  ui.step(4);
  assert.strictEqual(ui.state.comp.step, 4);
});

// Test 6: Save Batch & Persistence
test('6. Save Batch creates finalized containers', async () => {
  const ui = new DCLogic();
  ui.setAmount(ui.cat[0].id, 400);
  await ui.startComposer();
  ui.setState({ comp: Object.assign({}, ui.state.comp, { name: 'Кастомный ужин', mode: 'equal', count: 2 }) });
  
  await ui.save(false);
  assert.strictEqual(ui.state.route, 'preps');
  assert(ui.state.batches.length > 0);
  
  const latestBatch = ui.state.batches[0];
  assert.strictEqual(latestBatch.name, 'Кастомный ужин');
  assert.strictEqual(latestBatch.containers.length, 2);
});

// Test 7: Batch Filter Chips (В наличии, Свежие, Заканчиваются, Съедены)
test('7. Batches Filter Chips partition batches correctly', () => {
  const ui = new DCLogic();
  
  // Setup 3 batches: Fresh (3/3), Ending (1/3), Eaten (0/2)
  ui.state.batches = [
    {
      id: 'b1', name: 'Свежая партия', dateText: 'сегодня', totals: { g: 900, k: 600, p: 40, f: 10, c: 80 },
      containers: [
        { id: 'c1', n: 1, w: 300, left: 1, status: 'ready' },
        { id: 'c2', n: 2, w: 300, left: 1, status: 'ready' },
        { id: 'c3', n: 3, w: 300, left: 1, status: 'ready' }
      ]
    },
    {
      id: 'b2', name: 'Заканчивается', dateText: 'вчера', totals: { g: 600, k: 400, p: 30, f: 8, c: 50 },
      containers: [
        { id: 'c4', n: 1, w: 300, left: 0, status: 'consumed' },
        { id: 'c5', n: 2, w: 300, left: 1, status: 'ready' }
      ]
    },
    {
      id: 'b3', name: 'Съеденная партия', dateText: '2 дня назад', totals: { g: 600, k: 400, p: 30, f: 8, c: 50 },
      containers: [
        { id: 'c6', n: 1, w: 300, left: 0, status: 'consumed' },
        { id: 'c7', n: 2, w: 300, left: 0, status: 'consumed' }
      ]
    }
  ];
  
  // Default: В наличии (b1, b2)
  ui.setState({ prepChip: 'Все' });
  let vals = ui.renderVals();
  assert.strictEqual(vals.batches.length, 2);
  assert.strictEqual(vals.batches[0].name, 'Свежая партия');
  assert.strictEqual(vals.batches[1].name, 'Заканчивается');
  
  // Свежие: (b1)
  ui.setState({ prepChip: 'Свежие' });
  vals = ui.renderVals();
  assert.strictEqual(vals.batches.length, 1);
  assert.strictEqual(vals.batches[0].name, 'Свежая партия');
  
  // Заканчиваются: (b2)
  ui.setState({ prepChip: 'Заканчиваются' });
  vals = ui.renderVals();
  assert.strictEqual(vals.batches.length, 1);
  assert.strictEqual(vals.batches[0].name, 'Заканчивается');
  
  // Съедены: (b3)
  ui.setState({ prepChip: 'Съедены' });
  vals = ui.renderVals();
  assert.strictEqual(vals.batches.length, 1);
  assert.strictEqual(vals.batches[0].name, 'Съеденная партия');
});

// Test 8: Rename Batch Dialog
test('8. Rename Batch Dialog updates batch name', async () => {
  const ui = new DCLogic();
  ui.state.batches = [{
    id: 'b1', name: 'Старое имя', dateText: 'сегодня', totals: { g: 300, k: 300, p: 20, f: 5, c: 40 },
    containers: [{ id: 'c1', n: 1, w: 300, left: 1, status: 'ready' }]
  }];
  
  ui.openDlg('renameBatch', { id: 'b1', fields: { name: 'Старое имя' } });
  assert.strictEqual(ui.state.dialog.kind, 'renameBatch');
  
  ui.dlgField('name', 'Новое вкусное имя');
  const vals = ui.renderVals();
  await vals.onDlgConfirm();
  
  assert.strictEqual(ui.state.batches[0].name, 'Новое вкусное имя');
  assert.strictEqual(ui.state.dialog, null);
});

// Test 9: Container Consumption / Writeoff in Batch Modal
test('9. Writeoff container marks container as consumed', async () => {
  const ui = new DCLogic();
  ui.state.batches = [{
    id: 'b1', name: 'Партия', dateText: 'сегодня', totals: { g: 600, k: 600, p: 40, f: 10, c: 80 },
    containers: [
      { id: 'c1', n: 1, w: 300, left: 1, status: 'ready' },
      { id: 'c2', n: 2, w: 300, left: 1, status: 'ready' }
    ]
  }];
  
  // Open writeoff dialog for container 1
  ui.openDlg('writeoffContainer', { id: 'b1', cIdx: 0 });
  const vals = ui.renderVals();
  await vals.onDlgConfirm();
  
  assert.strictEqual(ui.state.batches[0].containers[0].left, 0);
  assert.strictEqual(ui.state.batches[0].containers[0].status, 'consumed');
  assert.strictEqual(ui.state.batches[0].containers[1].left, 1);
});

// Test 10: Packaged discrete item (2 packs x 130g) partial gram consumption and dynamic label
test('10. Packaged discrete item (2 packs x 130g) partial gram consumption and dynamic label', async () => {
  const ui = new DCLogic();
  
  // Simulated product and lot (2 packs of 130g yogurt)
  const mockLot = {
    id: 'yogurt-lot-1',
    display_name: 'Epica йогурт без сахара',
    remaining_quantity: 2.0,
    unit: 'pcs',
    product: {
      canonical_name: 'Epica йогурт без сахара',
      net_quantity: 130,
      net_unit: 'g',
      kcal_per_100: 90,
      protein_per_100: 10,
      fat_per_100: 4.8,
      carbs_per_100: 4
    }
  };
  
  const mapped = ui.mapBackendLot(mockLot);
  assert.strictEqual(mapped.avail, 260); // 2 * 130g = 260g
  assert.strictEqual(mapped.unit, 'г');
  assert.strictEqual(mapped.packSize, 130);
  
  ui.cat = [mapped];
  const getItem = (v) => {
    if (v.groups) {
      for (const g of v.groups) {
        if (g.items && g.items.length > 0) return g.items[0];
      }
    }
    return null;
  };

  let vals = ui.renderVals();
  const item = getItem(vals);
  assert.strictEqual(item.availText, '260 г (2 уп.)');
  
  // Partial consume 1 pack (130g)
  await ui.consumeLots([{ lot_id: 'yogurt-lot-1', quantity: 130, unit: 'g' }], 'consumed');
  assert.strictEqual(ui.avail(mapped), 130);
  vals = ui.renderVals();
  const itemAfter130 = getItem(vals);
  assert.strictEqual(itemAfter130.availText, '130 г (1 уп.)');
  
  // Partial consume half pack (65g)
  await ui.consumeLots([{ lot_id: 'yogurt-lot-1', quantity: 65, unit: 'g' }], 'consumed');
  assert.strictEqual(ui.avail(mapped), 65);
  vals = ui.renderVals();
  const itemAfter65 = getItem(vals);
  assert.strictEqual(itemAfter65.availText, '65 г (0,5 уп.)');
  
  // Consume final 65g -> item is depleted and moves to Закончились
  await ui.consumeLots([{ lot_id: 'yogurt-lot-1', quantity: 65, unit: 'g' }], 'consumed');
  assert.strictEqual(ui.avail(mapped), 0);
  ui.setState({ chip: 'Закончились' });
  vals = ui.renderVals();
  const itemEnded = getItem(vals);
  assert(itemEnded !== null);
  assert.strictEqual(itemEnded.availText, '0 г (закончился)');
});

console.log(`\n🎉 All ${passedTests} Web UI Logic Tests Passed Successfully!`);
