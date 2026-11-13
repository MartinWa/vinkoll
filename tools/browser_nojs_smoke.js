// Verify the ordinary-form fallback using the signed-in demo session.
async page => {
  const base = new URL(page.url()).origin;
  const browser = page.context().browser();
  const context = await browser.newContext({javaScriptEnabled: false, storageState: await page.context().storageState(), viewport: {width: 390, height: 844}});
  const plain = await context.newPage();
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  try {
    await plain.goto(base + '/wines/');
    await plain.locator('#q').fill('RIESLING');
    await plain.getByRole('button', {name: 'Sök', exact: true}).click();
    assert(await plain.locator('.wine-card').count() === 1, 'Search needs JavaScript');
    await plain.goto(base + '/settings/');
    await plain.locator('#export-wines').getByRole('button', {name: 'Skapa', exact: true}).click();
    assert((await plain.locator('#markdown-wines').inputValue()).includes('Riesling'), 'Catalogue generation needs JavaScript');
    const shelf = 'Etapp 2 utan JavaScript ' + Date.now();
    await plain.locator('#id_name').fill(shelf);
    await plain.locator('#id_name').locator('xpath=ancestor::form').getByRole('button', {name: 'Spara', exact: true}).click();
    assert(await plain.locator('.location-list li').filter({hasText: shelf}).count() === 1, 'Location form targets the wrong route after Markdown generation');
    await plain.locator('#export-location').selectOption('unassigned');
    await plain.locator('#export-bottles').getByRole('button', {name: 'Skapa', exact: true}).click();
    assert((await plain.locator('#markdown-bottles').inputValue()).includes('Location scope: Unassigned'), 'Bottle generation needs JavaScript');
    assert(await plain.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No-JavaScript mobile overflow');
    return 'Ordinary forms passed without JavaScript: local search, both Markdown outputs/scopes and location creation after generation.';
  } finally {
    await context.close();
  }
}
