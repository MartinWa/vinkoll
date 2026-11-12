// Run against the optional local demo using playwright-cli run-code --filename=tools/browser_smoke.js.
// The test changes synthetic demo stock, and creates/deletes an unused synthetic profile.
async page => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const baseUrl = page.url().startsWith('http') ? new URL(page.url()).origin : 'http://127.0.0.1:8003';
  await page.goto(baseUrl + '/');
  if (await page.locator('#id_username').count()) {
    await page.locator('#id_username').fill('demo');
    await page.locator('#id_password').fill('demo-vinkoll-local');
    await page.getByRole('button', {name: 'Logga in', exact: true}).click();
  }
  await page.setViewportSize({width: 390, height: 844});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile overflow');
  await page.getByRole('link', {name: 'Viner', exact: true}).click();
  await page.getByRole('link', {name: 'Lägg till vin', exact: true}).click();
  await page.locator('#id_name').fill('Exempel · Webbläsartest');
  await page.locator('#id_producer').fill('Syntetisk producent');
  await page.getByRole('button', {name: 'Spara', exact: true}).click();
  const card = page.locator('article').filter({hasText: 'Exempel · Webbläsartest'});
  assert(await card.count() === 1, 'Manual profile was not created');
  await page.getByRole('link', {name: 'Källare', exact: true}).click();
  assert(!await page.getByRole('link', {name: 'Exempel · Webbläsartest', exact: true}).count(), 'Profile created inventory');
  await page.getByRole('link', {name: 'Viner', exact: true}).click();
  await page.locator('article').filter({hasText: 'Exempel · Webbläsartest'}).getByRole('link', {name: 'Ta bort / arkivera'}).click();
  await page.getByRole('button', {name: 'Bekräfta', exact: true}).click();
  assert(!await page.getByRole('link', {name: 'Exempel · Webbläsartest', exact: true}).count(), 'Unused profile was not deleted');

  await page.getByRole('link', {name: 'Källare', exact: true}).click();
  await page.getByRole('link', {name: 'Lägg till flaskor', exact: true}).click();
  const option = page.locator('#id_wine option').filter({hasText: 'Exempel · Pinot noir'});
  await page.locator('#id_wine').selectOption(await option.getAttribute('value'));
  await page.locator('#id_quantity').fill('2');
  await page.locator('#id_vintage_kind').selectOption('year');
  await page.locator('#id_vintage_year').fill('2023');
  await page.locator('#id_purchase_price').fill('0');
  const originalToken = await page.locator('[name=token]').inputValue();
  await page.context().clearCookies({name: 'sessionid'});
  await page.getByRole('button', {name: 'Spara', exact: true}).click();
  await page.getByRole('heading', {name: 'Logga in igen'}).waitFor();
  await page.getByRole('link', {name: 'Logga in', exact: true}).click();
  await page.locator('#id_username').fill('demo');
  await page.locator('#id_password').fill('demo-vinkoll-local');
  await page.getByRole('button', {name: 'Logga in', exact: true}).click();
  assert(await page.locator('#id_quantity').inputValue() === '2', 'Expired form lost quantity');
  assert(await page.locator('#id_purchase_price').inputValue() === '0', 'Expired form lost zero price');
  assert(await page.locator('[name=token]').inputValue() === originalToken, 'Expired form lost operation token');
  await page.getByRole('button', {name: 'Spara', exact: true}).click();
  assert(await page.locator('[data-completed-operation]').count() === 1, 'Addition not confirmed');
  const pinot = page.locator('article').filter({hasText: 'Exempel · Pinot noir'});
  await pinot.getByRole('button', {name: 'Drick', exact: true}).click();
  await page.getByText('Välj vilken grupp du vill ta en flaska från.', {exact: true}).waitFor();
  const group = page.locator('label.group-choice').filter({hasText: '2023'}).first();
  await group.locator('input').check();
  await page.getByRole('button', {name: 'Drick en flaska', exact: true}).click();
  await pinot.getByRole('link', {name: 'Exempel · Pinot noir', exact: true}).click();
  const bottleGroup = page.locator('.bottle-group').filter({hasText: '2023'}).first();
  await bottleGroup.getByRole('link', {name: /Redigera flaska/}).first().click();
  const editUrl = page.url();
  const originalVersion = await page.locator('[name=version]').inputValue();
  const editToken = await page.locator('[name=token]').inputValue();
  const draftKey = 'vinkoll-draft:' + new URL(editUrl).pathname + new URL(editUrl).search;
  const concurrent = await page.context().newPage();
  try {
    await concurrent.goto(editUrl);
    await concurrent.locator('#id_vintage_year').fill('2024');
    await concurrent.getByRole('button', {name: 'Spara', exact: true}).click();
    assert(await concurrent.locator('[data-completed-operation]').count() === 1, 'Concurrent edit failed');
  } finally {
    await concurrent.close();
  }
  await page.locator('#id_vintage_year').fill('2022');
  await page.getByRole('button', {name: 'Spara', exact: true}).click();
  assert(await page.locator('.errorlist').count() > 0, 'Stale edit was accepted');
  assert(await page.locator('[data-discard-draft]').isVisible(), 'Stale edit has no discard path');
  assert(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key))?.token, draftKey) === editToken, 'Stale draft was lost');
  await page.reload();
  assert(await page.locator('[name=version]').inputValue() === originalVersion, 'Draft silently rebased a stale edit');
  await page.locator('[data-discard-draft]').click();
  assert(await page.locator('[name=version]').inputValue() === String(Number(originalVersion) + 1), 'Discard did not load the current version');
  assert(await page.locator('#id_vintage_year').inputValue() === '2024', 'Discard did not load current bottle details');
  assert(await page.locator('[name=token]').inputValue() !== editToken, 'Discard retained the old operation token');
  assert(await page.evaluate(key => sessionStorage.getItem(key), draftKey) === null, 'Discard retained the stale draft');
  await page.locator('#id_vintage_year').fill('2022');
  await page.getByRole('button', {name: 'Spara', exact: true}).click();
  assert(await page.locator('.bottle-group').filter({hasText: '2022'}).count() === 1, 'Single bottle edit failed');
  await page.getByRole('link', {name: 'Historik', exact: true}).click();
  assert(await page.getByRole('heading', {name: /Rättade flaska/}).count() > 0, 'Correction history missing');
  await page.getByRole('link', {name: 'Källare', exact: true}).click();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile overflow after mutation');
  await page.screenshot({path: 'test-results/cellar-mobile.png', fullPage: true});
  return 'Browser smoke passed: phone layout, profiles, expired form recovery, addition, group consumption, stale-draft discard, bottle editing, history.';
}
