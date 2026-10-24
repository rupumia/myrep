"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const usd = n => n == null ? "—" : n.toLocaleString("en-US", {style: "currency", currency: "USD", maximumFractionDigits: 0});
const cache = {};
async function getJSON(path) {
  if (path in cache) return cache[path];
  const p = fetch("data/" + path).then(r => r.ok ? r.json() : null).catch(() => null);
  cache[path] = p; return p;
}
const ord = n => { n = +n; const s = ["th","st","nd","rd"], v = n % 100; return n + (s[(v-20)%10] || s[v] || s[0]); };
const distLabel = (st, d) => d === "00" ? "At-large" : `${ord(d)} District`;
const fmtDate = d => d ? new Date(d + "T12:00:00").toLocaleDateString("en-US", {year:"numeric", month:"short", day:"numeric"}) : "";
const partyName = {D:"Democrat", R:"Republican", I:"Independent", L:"Libertarian", G:"Green"};

function voteBadge(v) {
  const cls = v === "Yea" ? "v-yea" : v === "Nay" ? "v-nay" : "v-nv";
  const icon = v === "Yea" ? "✓ " : v === "Nay" ? "✗ " : "– ";
  return `<span class="badge ${cls}"><span aria-hidden="true">${icon}</span>${esc(v)}</span>`;
}

function votesPanel(m) {
  if (m.votes == null) return `<div class="unavail">Voting records are unavailable right now (the data source failed during the last update).</div>`;
  if (!m.votes.length) return `<div class="unavail">No recorded votes found for this member in the most recent roll calls (they may be newly sworn in).</div>`;
  // Israel-related votes first (recent-first among themselves), then everything else in the existing order
  const isr = m.votes.filter(v => v.israel), rest = m.votes.filter(v => !v.israel);
  const votes = isr.concat(rest), show = Math.max(8, isr.length);
  const li = votes.map((v, i) => `<li ${i >= show ? 'hidden data-extra' : ''}${v.israel ? ' class="isr"' : ''}>${voteBadge(v.vote)}<div>
    ${v.israel ? `<span class="topic topic-isr" title="Matched: ${esc((v.israel_terms || []).join(", "))}. See About &amp; data for the keyword rule.">Israel-related</span>` : ""}
    <div class="vq">${v.bill ? (v.bill_url ? `<a href="${esc(v.bill_url)}" target="_blank" rel="noopener">${esc(v.bill)}</a> · ` : esc(v.bill) + " · ") : ""}${esc(v.question)}</div>
    ${v.israel_note ? `<div class="vnote">${esc(v.israel_note)}</div>` : ""}
    ${v.description ? `<div class="vd">${esc(v.description)}</div>` : ""}
    <div class="small">${fmtDate(v.date)} · Result: ${esc(v.result)}${v.yeas != null ? ` (${v.yeas}–${v.nays})` : ""} · <a href="${esc(v.source_url)}" target="_blank" rel="noopener">Roll call ${v.roll}</a></div></div></li>`).join("");
  const nRecent = rest.length + isr.filter(v => !v.older).length;
  const head = isr.length ? `<p class="small votes-note">${isr.length} Israel-related vote${isr.length > 1 ? "s" : ""} from this Congress shown first, then the ${nRecent} most recent votes. <a href="#about-israel">How votes are labeled</a></p>` : "";
  const more = votes.length > show ? `<button class="more" data-more>Show all ${votes.length} votes</button>` : "";
  return `${head}<ul class="votes">${li}</ul>${more}`;
}

function aipacFlags(f) {
  const a = f && f.aipac && f.aipac.status === "ok" ? f.aipac : {direct: 0, earmarked: 0, udp_support: 0, udp_oppose: 0};
  const got = a.direct + a.earmarked, out = [];
  if (got > 0) out.push(`<a class="flag flag-aipac" href="${esc(a.pac_url)}" target="_blank" rel="noopener" title="Direct ${usd(a.direct)} + earmarked via AIPAC PAC ${usd(a.earmarked)}. Source: FEC">Received AIPAC PAC money: ${usd(got)} (2025-26)</a>`);
  if (a.udp_support > 0) out.push(`<a class="flag flag-udp" href="${esc(a.udp_url)}" target="_blank" rel="noopener" title="Independent expenditures by United Democracy Project. Not money given to the campaign. Source: FEC">AIPAC-affiliated super PAC spent ${usd(a.udp_support)} supporting (2025-26)</a>`);
  if (a.udp_oppose > 0) out.push(`<a class="flag flag-udp" href="${esc(a.udp_url)}" target="_blank" rel="noopener" title="Independent expenditures by United Democracy Project. Not money given to the campaign. Source: FEC">AIPAC-affiliated super PAC spent ${usd(a.udp_oppose)} opposing (2025-26)</a>`);
  const d = f && f.defense;
  if (d && d.status === "ok" && d.total > 0) out.push(`<details class="flag flag-def"><summary>Received weapons-industry PAC money: ${usd(d.total)} (2025-26)</summary>
    <div class="flag-pop">${d.by_company.map(x => `<div>${esc(x.company)}: ${usd(x.total)}</div>`).join("")}<div class="small">Direct contributions from the listed defense contractors' corporate PACs. <a href="${esc(d.url)}" target="_blank" rel="noopener">Source: FEC →</a></div></div></details>`);
  return out.length ? `<div class="flags">${out.join("")}</div>` : "";
}

function defenseDetail(f) {
  const d = f && f.defense;
  let h = `<h4>Weapons-industry PAC money (2025–26)</h4>`;
  if (!d || d.status !== "ok") return h + `<div class="unavail">Not available in this update.</div>`;
  if (!(d.total > 0)) return h + `<div class="small">No direct contributions from the listed defense contractors' PACs reported in FEC bulk data for 2025–26. <a href="${esc(d.url)}" target="_blank" rel="noopener">Check on FEC</a> · <a href="#about-defense">Which companies?</a></div>`;
  return h + `<table class="aipac-t"><thead><tr><th>Company PAC</th><th class="num">Amount</th></tr></thead><tbody>` +
    d.by_company.map(x => `<tr><td><a href="https://www.fec.gov/data/committee/${esc(x.committee_id)}/?cycle=2026" target="_blank" rel="noopener">${esc(x.company)}</a></td><td class="num">${usd(x.total)}</td></tr>`).join("") +
    `<tr><th>Total</th><th class="num">${usd(d.total)}</th></tr></tbody></table><div class="small">Direct PAC contributions only; employee donations are not included here. <a href="${esc(d.url)}" target="_blank" rel="noopener">FEC records →</a> · <a href="#about-defense">Which companies?</a></div>`;
}

function aipacDetail(f) {
  const a = f && f.aipac;
  let h = `<h4>AIPAC-related money (2025–26)</h4>`;
  if (!a || a.status !== "ok") return h + `<div class="unavail">AIPAC-related FEC data is unavailable in this update.</div>`;
  const got = a.direct + a.earmarked;
  if (!got && !a.udp_support && !a.udp_oppose) return h + `<div class="small">No AIPAC PAC contributions (direct or earmarked) and no United Democracy Project outside spending reported for 2025–26. <a href="${esc(a.pac_url)}" target="_blank" rel="noopener">AIPAC PAC on FEC</a> · <a href="${esc(a.udp_url)}" target="_blank" rel="noopener">UDP spending on FEC</a></div>`;
  h += `<table class="aipac-t"><tbody>
    <tr><td>Direct contributions from AIPAC PAC</td><td class="num">${usd(a.direct)}</td></tr>
    <tr><td>Individual contributions earmarked through AIPAC PAC</td><td class="num">${usd(a.earmarked)}</td></tr>
    <tr><th>Received via AIPAC PAC, total</th><th class="num">${usd(got)}</th></tr>
  </tbody></table><div class="small">Net of refunds. <a href="${esc(a.pac_url)}" target="_blank" rel="noopener">AIPAC PAC disbursements on FEC →</a></div>
  <table class="aipac-t"><tbody>
    <tr><td>United Democracy Project (AIPAC-affiliated super PAC) outside spending supporting</td><td class="num">${usd(a.udp_support)}</td></tr>
    <tr><td>United Democracy Project outside spending opposing</td><td class="num">${usd(a.udp_oppose)}</td></tr>
  </tbody></table><div class="small">Outside spending is independent of the campaign and is not money the campaign received. <a href="${esc(a.udp_url)}" target="_blank" rel="noopener">UDP independent expenditures on FEC →</a> FEC data fetched ${esc(a.fetched)}.</div>`;
  return h;
}

function moneyBlock(f, opts = {}) {
  if (!f) return `<div class="unavail">Campaign finance data is unavailable for this person.</div>`;
  let h = "";
  if (f.available && f.totals) {
    const t = f.totals;
    h += `<div class="stats">
      <div class="stat"><b>${usd(t.receipts)}</b><span>Total raised</span></div>
      <div class="stat"><b>${usd(t.cash_on_hand)}</b><span>Cash on hand</span></div>
      <div class="stat"><b>${usd(t.individual)}</b><span>From individuals</span></div>
      <div class="stat"><b>${usd(t.pacs_other_committees)}</b><span>From PACs & other committees</span></div>
      <div class="stat"><b>${usd(t.party)}</b><span>From party committees</span></div>
      <div class="stat"><b>${usd(t.candidate_self)}</b><span>Self-funded (contributions + loans)</span></div>
    </div><div class="small">FEC 2025–2026 period, reports through ${esc(t.coverage_end || "n/a")}.</div>`;
  } else {
    h += `<div class="unavail">No FEC financial summary filed for the 2025–2026 period.</div>`;
  }
  h += `<h4>Top committees & PACs giving directly</h4>`;
  if (f.top_committees && f.top_committees.length) {
    h += `<table><thead><tr><th>Committee</th><th class="num">Amount</th></tr></thead><tbody>` +
      f.top_committees.slice(0, opts.n || 8).map(c => `<tr><td><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a>${c.connected_org && !c.name.toUpperCase().includes(c.connected_org.toUpperCase()) ? `<div class="small">${esc(c.connected_org)}</div>` : ""}</td><td class="num">${usd(c.total)}</td></tr>`).join("") + `</tbody></table>`;
  } else h += `<div class="unavail">No direct committee contributions reported in FEC bulk data for this cycle.</div>`;
  h += `<h4>Top employers of individual donors</h4>`;
  const e = f.top_employers;
  if (e && e.status === "ok" && e.items.length) {
    h += `<table><thead><tr><th>Employer</th><th class="num">Amount</th></tr></thead><tbody>` +
      e.items.slice(0, opts.n || 8).map(x => `<tr><td>${esc(x.employer)}</td><td class="num">${usd(x.total)}</td></tr>`).join("") +
      `</tbody></table><div class="small">Itemized donations ($200+), grouped by the employer donors reported. FEC data fetched ${esc(e.fetched)}.</div>`;
  } else if (e && e.status === "ok") h += `<div class="unavail">No itemized individual contributions reported yet.</div>`;
  else h += `<div class="unavail">Employer breakdown not available yet (FEC API rate limit; filled in on later updates). See the FEC page below.</div>`;
  h += aipacDetail(f);
  h += defenseDetail(f);
  h += `<p class="links"><a href="${esc(f.fec_url)}" target="_blank" rel="noopener">Full FEC record →</a></p>`;
  return h;
}

function memberCard(m, note) {
  const where = m.chamber === "senate" ? `${m.state} · ${m.state_rank ? m.state_rank[0].toUpperCase() + m.state_rank.slice(1) + " senator" : "Senator"}`
    : `${m.state} · ${distLabel(m.state, String(m.district).padStart(2, "0"))}`;
  const id = "m-" + m.bioguide;
  return `<article class="card" id="${id}">
    <div class="card-top">
      <img class="photo" src="${esc(m.photo)}" alt="Official photo of ${esc(m.name)}" loading="lazy" onerror="this.style.visibility='hidden'">
      <div>
        <h3>${esc(m.name)}<span class="party" title="${esc(m.party)}">${esc(m.party_abbr)}</span></h3>
        <div class="meta">${esc(m.title)} · ${esc(where)}</div>
        <div class="meta">${esc(m.party)} · term ends ${fmtDate(m.term_end)}</div>
        ${note ? `<div class="meta"><em>${esc(note)}</em></div>` : ""}
        ${aipacFlags(m.finance)}
        <div class="links">${m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">Website</a>` : ""}${m.phone ? `<a href="tel:${esc(m.phone)}">${esc(m.phone)}</a>` : ""}<a href="${esc(m.bioguide_url)}" target="_blank" rel="noopener">Bio</a></div>
      </div>
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected="true" data-tab="votes">Recent votes</button>
      <button role="tab" aria-selected="false" data-tab="money">Campaign money</button>
    </div>
    <div class="panel" data-panel="votes">${votesPanel(m)}</div>
    <div class="panel" data-panel="money" hidden>${moneyBlock(m.finance)}</div>
  </article>`;
}

function raceBlock(race, members, title) {
  if (!race) return `<div class="race"><h3>${esc(title)}</h3><div class="unavail">2026 candidate data is unavailable for this seat.</div></div>`;
  const filed = race.candidates.filter(c => c.finance.available && c.finance.totals && c.finance.totals.receipts > 0);
  const rest = race.candidates.length - filed.length;
  const rows = filed.map(c => {
    const st = c.status === "Incumbent" ? "st-inc" : c.status === "Challenger" ? "st-ch" : "st-open";
    const rec = c.bioguide ? (members[c.bioguide] ? `Current member of Congress: voting record is on ${esc(members[c.bioguide].name)}'s card above.` : `Current member of Congress (another seat or district); <a href="https://bioguide.congress.gov/search/bio/${esc(c.bioguide)}" target="_blank" rel="noopener">see bio</a>.`)
      : "No congressional voting record (not a current member of Congress).";
    return `<tr><td><strong>${esc(c.name)}</strong> <span class="party" title="${esc(c.party)}">${esc(c.party_abbr)}</span><br>
      <span class="status ${st}">${esc(c.status === "Unknown" ? "Status not listed" : c.status)}</span>${c.bioguide ? ` <span class="status st-open">Current member</span>` : ""}${aipacFlags(c.finance)}
      <details class="cand"><summary>Donors & details</summary><p class="small">${rec}</p>${moneyBlock(c.finance, {n: 5})}</details></td>
      <td class="num">${usd(c.finance.totals.receipts)}</td><td class="num hide-sm">${usd(c.finance.totals.cash_on_hand)}</td></tr>`;
  }).join("");
  return `<div class="race"><h3>${esc(title)}</h3>
    ${race.fec_open_seat_signal ? `<p class="notice">The FEC lists most other candidates here as running for an <em>open seat</em>, which usually means the incumbent is not seeking re-election, even though the incumbent's campaign committee is still registered.</p>` : ""}
    <p class="small">Candidates registered with the FEC for 2026 who have reported raising money, sorted by total raised. May include candidates who lost a primary or withdrew.${rest > 0 ? ` ${rest} other registered filer(s) reported no money raised and are not listed.` : ""}</p>
    ${filed.length ? `<table><thead><tr><th>Candidate</th><th class="num">Raised</th><th class="num hide-sm">Cash on hand</th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="unavail">No candidates have reported raising money for this seat yet.</div>`}
  </div>`;
}

async function lookup(zip) {
  const res = $("#results"), msg = $("#form-msg");
  msg.textContent = "";
  if (!/^\d{5}$/.test(zip)) { msg.textContent = "Please enter a 5-digit ZIP code."; return; }
  history.replaceState(null, "", "?zip=" + zip);
  res.innerHTML = `<p class="skeleton">Looking up ZIP ${zip}…</p>`;
  const meta = await getJSON("meta.json");
  const known = !meta || !meta.zip_prefixes || meta.zip_prefixes.includes(zip.slice(0, 3));
  const shard = known ? await getJSON(`zip/${zip.slice(0, 3)}.json`) : null;
  const entry = shard && shard[zip];
  const dists = entry && entry.d;
  if (!dists) { res.innerHTML = `<div class="notice err">We couldn't find ZIP ${esc(zip)} in the Census ZIP code areas. PO-box-only and some business ZIPs aren't mapped; try your home ZIP or use <a href="https://www.house.gov/representatives/find-your-representative">house.gov's lookup</a>.</div>`; return; }
  const stateCodes = [...new Set(dists.map(d => d.state))];
  const states = Object.fromEntries(await Promise.all(stateCodes.map(async s => [s, await getJSON(`states/${s}.json`)])));
  const ids = new Set();
  for (const s of stateCodes) (states[s]?.senators || []).forEach(b => ids.add(b));
  for (const d of dists) { const b = states[d.state]?.house?.[d.district]; if (b) ids.add(b); }
  const members = Object.fromEntries((await Promise.all([...ids].map(async b => [b, await getJSON(`members/${b}.json`)]))));
  const raceKeys = [];
  for (const s of stateCodes) if (states[s]?.senate_race_2026) raceKeys.push(`${s}-S`);
  const redrawn = entry.d26 !== undefined;
  const dists26 = redrawn ? (entry.d26 || []) : dists;
  for (const d of dists26) raceKeys.push(`${d.state}-${d.district}`);
  const races = Object.fromEntries(await Promise.all(raceKeys.map(async k => [k, await getJSON(`races/${k}.json`)])));

  let h = "";
  const sname = s => states[s]?.name || s;
  h += `<div class="loc"><h2>ZIP ${esc(zip)}</h2><p>${dists.map(d => `${esc(sname(d.state))} · ${distLabel(d.state, d.district)}`).join(" / ")}</p></div>`;
  if (dists.length > 1) h += `<div class="notice"><strong>This ZIP code is split across ${dists.length} congressional districts.</strong> We're showing every possible House member: ${dists.map(d => `${esc(d.state)}-${d.district === "00" ? "AL" : esc(d.district)} (~${Math.round(d.land_share * 100)}% of the ZIP's land area)`).join(", ")}. Check your exact address at <a href="https://www.house.gov/representatives/find-your-representative" target="_blank" rel="noopener">house.gov</a>.</div>`;

  const sens = stateCodes.flatMap(s => states[s]?.senators || []);
  const nonVoting = stateCodes.every(s => ["DC","PR","AS","GU","MP","VI"].includes(s));
  h += `<h2 class="section">Your senators</h2>`;
  h += sens.length ? `<div class="grid">${sens.map(b => members[b] ? memberCard(members[b]) : `<div class="card"><div class="panel unavail">Member data unavailable.</div></div>`).join("")}</div>`
    : `<div class="unavail">${nonVoting ? "This area has no U.S. senators." : "Senator data unavailable."}</div>`;
  h += `<h2 class="section">Your House ${dists.length > 1 ? "representatives (possible)" : "representative"}</h2><div class="grid">`;
  for (const d of dists) {
    const b = states[d.state]?.house?.[d.district];
    h += b && members[b] ? memberCard(members[b], dists.length > 1 ? `Covers ~${Math.round(d.land_share * 100)}% of this ZIP's land area` : "")
      : `<div class="card"><div class="panel"><h3>${esc(d.state)} ${distLabel(d.state, d.district)}</h3><div class="unavail">This seat is currently vacant or member data is unavailable.</div></div></div>`;
  }
  h += `</div>`;
  h += `<h2 class="section">Running in 2026</h2>
    <p class="small">Challengers have no congressional voting record. Several states redrew House maps for 2026, so district numbers below may cover a different area than today.</p>`;
  for (const s of stateCodes) {
    if (states[s]?.senate_race_2026) h += raceBlock(races[`${s}-S`], members, `U.S. Senate · ${sname(s)}`);
  }
  const noSen = stateCodes.filter(s => !states[s]?.senate_race_2026 && states[s]?.senators?.length);
  if (noSen.length) h += `<p class="small">No U.S. Senate seat from ${noSen.map(sname).join(", ")} is on the 2026 ballot.</p>`;
  if (redrawn) {
    h += `<div class="notice"><strong>${esc(sname(dists[0].state))} redrew its congressional map for the 2026 election.</strong> ` +
      (entry.d26 && entry.d26.length ? `Under the new map this ZIP is in ${dists26.map(d => `${esc(d.state)}-${d.district === "00" ? "AL" : esc(d.district)}${dists26.length > 1 ? ` (~${Math.round(d.land_share * 100)}%)` : ""}`).join(", ")}. The House race below is for the new district, which may differ from your current one.`
        : `We could not determine this ZIP's new district, so the 2026 House race is unavailable here. Check your state's election office.`) + `</div>`;
  }
  if (dists26.length > 1 && redrawn) h += `<p class="small">This ZIP is split under the 2026 map; every possible race is shown.</p>`;
  for (const d of dists26) h += raceBlock(races[`${d.state}-${d.district}`], members, `U.S. House · ${sname(d.state)} ${distLabel(d.state, d.district)}${redrawn ? " (2026 map)" : ""}`);
  res.innerHTML = h;
}

document.addEventListener("click", e => {
  const t = e.target.closest("[data-tab]");
  if (t) {
    const card = t.closest(".card");
    card.querySelectorAll("[data-tab]").forEach(b => b.setAttribute("aria-selected", b === t));
    card.querySelectorAll("[data-panel]").forEach(p => p.hidden = p.dataset.panel !== t.dataset.tab);
  }
  const m = e.target.closest("[data-more]");
  if (m) { m.parentElement.querySelectorAll("[data-extra]").forEach(li => li.hidden = false); m.remove(); }
});
$("#zip-form").addEventListener("submit", e => { e.preventDefault(); lookup($("#zip").value.trim()); });

(async () => {
  const meta = await getJSON("meta.json");
  if (meta) {
    $("#updated").textContent = new Date(meta.built_at).toLocaleDateString("en-US", {year: "numeric", month: "long", day: "numeric"});
    const s = meta.sources || {};
    const items = [];
    const add = (k, extra) => s[k] && items.push(`<li><a href="${esc(s[k].url)}" target="_blank" rel="noopener">${esc(s[k].name)}</a>${extra ? " — " + extra : ""}</li>`);
    add("legislators"); add("zip");
    add("zip_2026", meta.redistricted_2026?.length ? `used for 2026 House races in ${meta.redistricted_2026.join(", ")}` : "");
    add("house_votes", s.house_votes?.latest_vote_date ? `latest vote ${fmtDate(s.house_votes.latest_vote_date)}` : "");
    add("senate_votes", s.senate_votes?.latest_vote_date ? `latest vote ${fmtDate(s.senate_votes.latest_vote_date)} (Voteview can lag the Senate by days to weeks)` : "");
    add("fec", s.fec?.coverage_through ? `reports through ${esc(s.fec.coverage_through)}` : "");
    add("aipac", s.aipac?.status === "ok" ? `fetched ${esc(s.aipac.retrieved)}` : "unavailable in this update");
    if (meta.israel_keywords && meta.israel_keywords.length) $("#israel-keywords").textContent = meta.israel_keywords.join(", ");
    if (meta.defense_pacs) $("#defense-list").innerHTML = meta.defense_pacs.companies.map(c => `<li>${esc(c.company)}: <a href="https://www.fec.gov/data/committee/${esc(c.committee_id)}/" target="_blank" rel="noopener">${esc(c.fec_name)} (${esc(c.committee_id)})</a></li>`).join("");
    add("fec_api", s.fec_api ? `employer breakdowns cover ${s.fec_api.committees_covered} of ${s.fec_api.committees_total} campaigns so far` : "");
    $("#sources-list").innerHTML = items.join("") + (meta.warnings || []).map(w => `<li class="notice err">${esc(w)}</li>`).join("");
  } else {
    $("#updated").textContent = "unavailable";
  }
  const z = new URLSearchParams(location.search).get("zip");
  if (z) { $("#zip").value = z; lookup(z); }
})();
