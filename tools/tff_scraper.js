// Collects the home matches of Galatasaray, Fenerbahçe and Beşiktaş from tff.org.
// Usage: open https://www.tff.org/default.aspx?pageID=198 in a browser, open the developer
// console (F12), paste this file and press Enter. When it finishes it downloads
// tff_home_matches_compact.txt (format described in tools/build_fixtures.py).
// tff.org pages are windows-1254 encoded ASP.NET pages: the season list is a postback form
// (module m_28_398 on the club page) and the result grid is paged (20 rows per page).

(async () => {
  const CLUBS = { 3604: 'GALATASARAY', 3592: 'FENERBAH', 3590: 'BEŞİKTAŞ' };          // kulupID
  const SEASONS = [['20', '2020-2021', 6], ['22', '2022-2023', 4], ['23', '2023-2024', 3], ['24', '2024-2025', 2]];
  const PRE = 'ctl00$MPane$m_28_398_ctnr$m_28_398$';

  const get = async (u) => { const r = await fetch(u); return new TextDecoder('windows-1254').decode(await r.arrayBuffer()); };
  const post = async (u, p) => { const r = await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: p.toString() });
    return new TextDecoder('windows-1254').decode(await r.arrayBuffer()); };
  const dom = (h) => new DOMParser().parseFromString(h, 'text/html');
  const formParams = (d) => { const p = new URLSearchParams();
    for (const x of d.querySelector('form').querySelectorAll('input,select,textarea')) {
      if (!x.name || ['submit', 'image', 'button'].includes(x.type)) continue;
      if ((x.type === 'checkbox' || x.type === 'radio') && !x.checked) continue;
      p.append(x.name, x.value || ''); } return p; };
  const parseGrid = (d) => { const g = d.querySelector('[id*="grdFikstur"]'); if (!g) return { rows: [], next: null };
    const rows = []; for (const tr of g.querySelectorAll('tr')) { const td = [...tr.querySelectorAll('td')]; if (td.length < 6) continue;
      const a = tr.querySelector('a[href*="macID"]');
      rows.push({ hafta: td[0].textContent.trim(), home: td[1].textContent.trim(), score: td[2].textContent.trim(),
        away: td[3].textContent.trim(), org: td[5].textContent.trim(), macID: a ? (a.getAttribute('href').match(/macID=(\d+)/i) || [])[1] : null }); }
    const nx = [...g.querySelectorAll('a')].find((a) => /Sonraki/.test(a.textContent));
    return { rows, next: nx ? (nx.getAttribute('href').match(/__doPostBack\('([^']+)'/) || [])[1] : null }; };

  async function clubSeason(cid, sv, st, si) {
    const url = '/Default.aspx?pageId=28&kulupID=' + cid;
    let p = formParams(dom(await get(url)));
    p.set(PRE + 'SezonSelector1$combo_Input', st); p.set(PRE + 'SezonSelector1$combo_text', st);
    p.set(PRE + 'SezonSelector1$combo_value', sv); p.set(PRE + 'SezonSelector1$combo_index', String(si));
    p.set(PRE + 'bntAra', 'Ara');
    let d = dom(await post(url, p)); const all = new Map();
    for (const r of parseGrid(d).rows) all.set(r.macID, r);
    for (let guard = 0; guard < 8; guard++) {                      // follow "Sonraki" (next page)
      const nx = parseGrid(d).next; if (!nx) break; let got = null;
      for (let attempt = 0; attempt < 3 && !got; attempt++) {      // a page sometimes repeats: retry
        const pp = formParams(d); pp.set('__EVENTTARGET', nx); pp.set('__EVENTARGUMENT', ''); pp.delete(PRE + 'bntAra');
        const dd = dom(await post(url, pp)); const rows = parseGrid(dd).rows;
        if (rows.some((r) => !all.has(r.macID))) { got = dd; rows.forEach((r) => all.set(r.macID, r)); } }
      if (!got) break; d = got; }
    return [...all.values()]; }

  const home = [];
  for (const [cid, pat] of Object.entries(CLUBS)) for (const [sv, st, si] of SEASONS)
    for (const r of await clubSeason(cid, sv, st, si)) if (r.macID && new RegExp(pat).test(r.home)) home.push(r);
  const seen = new Set(); const uniq = home.filter((r) => !seen.has(r.macID) && seen.add(r.macID));

  for (const r of uniq) {                                           // match page: date, time, stadium
    const d = dom(await get('/Default.aspx?pageID=29&macID=' + r.macID));
    const g = (s) => (d.querySelector('[id$="' + s + '"]') || { textContent: '' }).textContent.replace(/\s+/g, ' ').trim();
    Object.assign(r, { tarih: g('dtMacBilgisi_lblTarih'), stad: g('dtMacBilgisi_lnkStad'), org2: g('dtMacBilgisi_lblOrganizasyonAdi') }); }

  const vk = (s) => /ALİ SAMİ|RAMS PARK|TÜRK TELEKOM/.test(s) ? 'R' : /SARACO|ÜLKER/.test(s) ? 'S' : /VODAFONE|BEŞİKTAŞ PARK|TÜPRAŞ/.test(s) ? 'T' : 'X';
  const hk = (s) => /GALATASARAY/.test(s) ? 'GS' : /FENERBAH/.test(s) ? 'FB' : 'BJK';
  const ck = (s) => /Süper Kupa/.test(s) ? 'S' : /Kupas/.test(s) ? 'C' : 'L';
  const lines = uniq.sort((a, b) => +a.macID - +b.macID).map((r) => {
    const m = (r.tarih || '').match(/(\d{1,2})\.(\d{1,2})\.(\d{4})\s*-\s*(\d{1,2}):(\d{2})/);
    const dt = m ? `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')} ${m[4].padStart(2, '0')}:${m[5]}` : '-';
    const rnd = ((r.org2 || '').match(/\(([^)]*(Tur|Final|Grup|Eleme)[^)]*)\)\s*$/) || [])[1] || r.hafta;
    return [r.macID, dt, vk(r.stad), ck(r.org2), rnd, hk(r.home), r.away, r.score].join('|'); });
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'tff_home_matches_compact.txt' });
  document.body.appendChild(a); a.click();
  console.log('done:', lines.length, 'home matches');
})();
