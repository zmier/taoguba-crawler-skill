// Read the site's own rendered cells. The Python runner supplies the scoped session on stdin.
const fs = require('node:fs');
const { chromium } = require('playwright');
const tabs = {
  持仓: ['#chi_column', 'listChiCangMatch'],
  收益明细: ['#income_column', 'listIncome'],
  交割单: ['#jiao_column', 'listDelivertMatch'],
};

async function readPage(page, name, n, select) {
  const [selector, endpoint] = tabs[name];
  const received = page.waitForResponse((r) => {
    const u = new URL(r.url());
    return (
      u.origin === 'https://www.tgb.cn' &&
      u.pathname === '/spmatch/gains/' + endpoint &&
      u.searchParams.get('pageNo') === String(n)
    );
  });
  const [response] = await Promise.all([received, select()]);
  const json = await response.json();
  if (!response.ok() || !json.status || !Array.isArray(json.dto?.list))
    throw Error('表格不可读或会话已失效');
  const total = Number(json.dto.pageNum);
  if (!Number.isInteger(total) || total < 0 || (n > total && !(n === 1 && total === 0)))
    throw Error('分页信息不符');
  // The response event precedes the site's callback. Wait for the rendered page, including a valid empty tab.
  await page.waitForFunction(
    ({ selector, n, total, rows }) => {
      const table = document.querySelector(selector);
      return (
        table?.querySelector('tr th') &&
        (rows === 0 || table.querySelector('tr td')) &&
        (total === 0 || Number(document.querySelector('#pageNo')?.innerText) === n)
      );
    },
    { selector, n, total, rows: json.dto.list.length },
  );
  const table = await page
    .locator(selector)
    .evaluate((node) =>
      [...node.querySelectorAll('tr')].map((tr) =>
        [...tr.children].map((cell) => ({
          value: cell.innerText.trim(),
          span: cell.rowSpan || 1,
          hidden: getComputedStyle(cell).display === 'none',
          action: cell.querySelector('span[onclick^="selectImageList"]')?.getAttribute('onclick') || '',
        })),
      ),
    );
  if (table[0]?.[0]?.value !== '日期' || (json.dto.list.length && table.length < 2))
    throw Error('无法核对渲染表头或数据行');
  return { total, table };
}

async function main() {
  const { uid, cookie, cards, username, interval } = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const ctx = await browser.newContext();
    await ctx.addCookies(
      cookie
        .split(';')
        .map((s) => s.trim())
        .filter((s) => s.includes('='))
        .map((s) => ({
          url: 'https://www.tgb.cn',
          name: s.slice(0, s.indexOf('=')),
          value: s.slice(s.indexOf('=') + 1),
        })),
    );
    const results = [];
    for (const card of cards) {
      const url = new URL(card.url);
      const seq = url.searchParams.get('spmatchSeq');
      if (
        url.origin !== 'https://www.tgb.cn' ||
        url.pathname !== '/spmatch/gains/readInfo' ||
        !/^\d+$/.test(seq) ||
        url.searchParams.get('lookeUserID') !== uid
      )
        throw Error('赛事地址或作者 ID 不符');
      const page = await ctx.newPage();
      await page.goto(card.url, { waitUntil: 'domcontentloaded' });
      const identity = page.locator('#datamsg');
      if (
        (await identity.count()) !== 1 ||
        (await identity.getAttribute('data-lookeuserID')) !== uid ||
        (await identity.getAttribute('data-spmatchSeq')) !== seq
      )
        throw Error('战绩页不可见或身份不符');
      const athlete = await page.locator('.user-name[data-userName]').getAttribute('data-userName');
      if (!athlete || (username && username !== athlete)) throw Error('参赛昵称不符');
      const body = await page.locator('body').innerText();
      const summary = body.split('查看全部选手')[1]?.split('净值走势图')[0]?.trim();
      if (!summary?.includes(athlete)) throw Error('缺少参赛摘要');
      const labels = (await page.locator('.match-data-nav:visible').allTextContents()).map((t) =>
        t.trim(),
      );
      if (
        !labels.includes('收益明细') ||
        !labels.some((x) => x === '交割单' || x === '持仓') ||
        labels.some((x) => !tabs[x])
      )
        throw Error('赛事栏目变化，请核对来源');
      const captured = {};
      for (const name of labels) {
        const tab = page.locator('.match-data-nav:visible').filter({ hasText: name });
        const first = await readPage(page, name, 1, () => tab.click());
        const pages = [first.table];
        for (let n = 2; n <= first.total; n++) {
          await new Promise((resolve) => setTimeout(resolve, interval * 1000));
          const next = await readPage(page, name, n, () => page.evaluate((n) => window.listPage(n), n));
          if (next.total !== first.total) throw Error('读取期间页数变化');
          pages.push(next.table);
        }
        captured[name] = pages;
      }
      results.push({ url: card.url, seq, athlete, summary, tables: captured });
      await page.close();
    }
    process.stdout.write(JSON.stringify(results));
  } finally {
    await browser.close();
  }
}
main().catch((e) => {
  console.error(e.message);
  process.exitCode = 1;
});
