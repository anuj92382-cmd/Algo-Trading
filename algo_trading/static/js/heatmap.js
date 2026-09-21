/**
 * heatmap.js - Sector Heatmap Logic
 * Aaj kaunsa sector teji mein hai, kaunsa mandi mein
 */

let _hmData = [];

// ─── LOAD HEATMAP ────────────────────────────────────────────
async function loadHeatmap() {
    const grid = document.getElementById('hm-grid');
    if (!grid) return;

    grid.innerHTML = `
        <div class="hm-loading">
            <div class="hm-spinner"></div>
            <b>Sector data load ho raha hai...</b><br>
            <span style="color:var(--text3);font-size:12px">
                NSE se live prices fetch ho rahe hain
            </span>
        </div>`;

    // Reset summary
    setText('hm-bull-count',   '...');
    setText('hm-bear-count',   '...');
    setText('hm-neut-count',   '...');
    setText('hm-best-sector',  '...');
    setText('hm-worst-sector', '...');

    const data = await api('/api/sector/heatmap');

    if (!data || data.error) {
        const errMsg = data?.error || 'Data load nahi hua';
        const isPlan = errMsg.includes('permission') || errMsg.includes('Insufficient');
        grid.innerHTML = `
            <div class="hm-loading">
                <div style="font-size:40px;margin-bottom:12px">⚠️</div>
                <b style="color:var(--yellow)">${isPlan ? 'Live Data Unavailable' : 'Error'}</b><br>
                <p style="color:var(--text3);font-size:13px;max-width:400px;margin:10px auto 0">
                    ${isPlan
                        ? 'Live market data ke liye Kite Connect plan "Personal" se "Connect" pe upgrade karo.<br><br>developers.kite.trade pe apni app edit karo.'
                        : errMsg}
                </p>
            </div>`;
        return;
    }

    _hmData = data.sectors || [];
    if (!_hmData.length) {
        grid.innerHTML = `<div class="hm-loading">Koi sector data nahi mila. Market band hai?</div>`;
        return;
    }

    // Update summary
    const bulls = _hmData.filter(s => s.strength === 'BULLISH').length;
    const bears = _hmData.filter(s => s.strength === 'BEARISH').length;
    const neuts = _hmData.filter(s => s.strength === 'NEUTRAL').length;

    setText('hm-bull-count',   bulls);
    setText('hm-bear-count',   bears);
    setText('hm-neut-count',   neuts);
    setText('hm-timestamp',    `Updated: ${data.timestamp}`);

    if (_hmData.length > 0) {
        const best  = _hmData[0];
        const worst = _hmData[_hmData.length - 1];
        setText('hm-best-sector',  `${best.sector} (${best.avg_change > 0 ? '+' : ''}${best.avg_change}%)`);
        setText('hm-worst-sector', `${worst.sector} (${worst.avg_change > 0 ? '+' : ''}${worst.avg_change}%)`);
    }

    // Render heatmap tiles
    _renderHeatmap(_hmData);
}

// ─── RENDER HEATMAP ──────────────────────────────────────────
function _renderHeatmap(sectors) {
    const grid = document.getElementById('hm-grid');
    if (!grid) return;

    grid.innerHTML = sectors.map(s => _heatmapTile(s)).join('');
}

function _heatmapTile(s) {
    const chg      = s.avg_change || 0;
    const absChg   = Math.abs(chg);
    const sign     = chg >= 0 ? '+' : '';
    const isBull   = s.strength === 'BULLISH';
    const isBear   = s.strength === 'BEARISH';

    // Color intensity based on change magnitude
    let bgColor, textColor, borderColor;
    if (isBull) {
        const intensity = Math.min(absChg / 3, 1);   // cap at 3%
        const r = Math.round(5  + intensity * 5);
        const g = Math.round(46 + intensity * 150);
        const b = Math.round(22 + intensity * 30);
        bgColor     = `rgba(${r},${g},${b},${0.15 + intensity * 0.35})`;
        textColor   = `rgb(${Math.round(74+intensity*100)},${Math.round(222-intensity*30)},${Math.round(128-intensity*30)})`;
        borderColor = `rgba(34,197,94,${0.2 + intensity * 0.4})`;
    } else if (isBear) {
        const intensity = Math.min(absChg / 3, 1);
        bgColor     = `rgba(${Math.round(120+intensity*80)},7,7,${0.15 + intensity * 0.35})`;
        textColor   = `rgb(${Math.round(252-intensity*50)},${Math.round(165-intensity*80)},${Math.round(165-intensity*80)})`;
        borderColor = `rgba(239,68,68,${0.2 + intensity * 0.4})`;
    } else {
        bgColor     = 'rgba(30,45,65,0.5)';
        textColor   = '#94a3b8';
        borderColor = 'rgba(30,53,85,0.5)';
    }

    const upPct = s.up_pct || 0;
    const emoji = isBull ? '📈' : isBear ? '📉' : '➡️';

    // Top gainer / loser
    const gainStr = s.top_gainer?.symbol
        ? `<span class="hm-top-stock green">▲ ${s.top_gainer.symbol} +${s.top_gainer.chg}%</span>`
        : '';
    const lossStr = s.top_loser?.symbol
        ? `<span class="hm-top-stock red">▼ ${s.top_loser.symbol} ${s.top_loser.chg}%</span>`
        : '';

    return `
<div class="hm-tile"
     style="background:${bgColor};border-color:${borderColor}"
     onclick="loadSectorDetail('${s.sector}')">

    <div class="hm-tile-head">
        <span class="hm-sector-name">${emoji} ${s.sector}</span>
        <span class="hm-tile-badge" style="color:${textColor};background:${borderColor.replace('rgba','rgba').replace(/,[^,]+\)$/,',0.15)')}">
            ${s.strength}
        </span>
    </div>

    <div class="hm-tile-change" style="color:${textColor}">
        ${sign}${chg.toFixed(2)}%
    </div>

    <div class="hm-tile-bar-wrap">
        <div class="hm-tile-bar-bg">
            <div class="hm-tile-bar-fill"
                 style="width:${upPct}%;background:${isBull ? 'var(--green)' : isBear ? 'var(--red)' : 'var(--text3)'}">
            </div>
        </div>
        <span class="hm-tile-ratio" style="color:${textColor}">
            ${s.up_stocks}↑ ${s.dn_stocks}↓
        </span>
    </div>

    <div class="hm-tile-stocks">
        ${gainStr}
        ${lossStr}
    </div>

    <div class="hm-tile-footer">
        <span class="hm-tile-total">${s.total} stocks</span>
        <span class="hm-tile-action">Click for detail →</span>
    </div>
</div>`;
}

// ─── SECTOR DETAIL ───────────────────────────────────────────
async function loadSectorDetail(sectorName) {
    const detail = document.getElementById('hm-detail');
    const tbody  = document.getElementById('hm-detail-body');
    const title  = document.getElementById('hm-detail-title');

    if (!detail || !tbody) return;

    if (title) title.textContent = `${sectorName} — Stocks`;
    if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="empty">⏳ Loading...</td></tr>';
    detail.style.display = 'block';

    // Scroll to detail
    detail.scrollIntoView({ behavior: 'smooth', block: 'start' });

    const data = await api(`/api/sector/stocks?name=${encodeURIComponent(sectorName)}`);

    if (!data || data.error || !data.stocks?.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty red">
            ${data?.error || 'Koi data nahi mila'}</td></tr>`;
        return;
    }

    tbody.innerHTML = data.stocks.map(s => {
        const chg    = s.change_pct || 0;
        const cc     = chg > 0 ? 'green' : chg < 0 ? 'red' : 'dim';
        const sign   = chg > 0 ? '+' : '';
        const hasLtp = s.ltp > 0;

        return `<tr>
            <td><b>${s.symbol}</b></td>
            <td>${hasLtp ? '₹' + s.ltp.toFixed(2) : '--'}</td>
            <td class="${cc}"><b>${hasLtp ? sign + chg.toFixed(2) + '%' : '--'}</b></td>
            <td class="dim">${s.open  > 0 ? '₹' + s.open.toFixed(2)  : '--'}</td>
            <td class="green">${s.high > 0 ? '₹' + s.high.toFixed(2) : '--'}</td>
            <td class="red">${s.low   > 0 ? '₹' + s.low.toFixed(2)   : '--'}</td>
            <td class="dim">${s.volume > 0 ? fmtVol(s.volume) : '--'}</td>
            <td>
                <button class="btn-sm btn-add"
                        onclick="addToWatchlist('${s.symbol}')">+ Watch</button>
                <button class="btn-sm btn-blue" style="margin-left:4px"
                        onclick="quickAnalyseFromHeatmap('${s.symbol}')">⚡ Scan</button>
            </td>
        </tr>`;
    }).join('');
}

function closeHmDetail() {
    const d = document.getElementById('hm-detail');
    if (d) d.style.display = 'none';
}

async function quickAnalyseFromHeatmap(symbol) {
    // Switch to scanner page and run quick analyse
    showPage('scanner');
    const inp = document.getElementById('sc-quick-sym');
    if (inp) inp.value = symbol;
    await quickAnalyse();
}

// ─── SORT HEATMAP ────────────────────────────────────────────
function sortHeatmap(by) {
    if (!_hmData.length) return;
    let sorted = [..._hmData];
    if (by === 'bull')  sorted.sort((a, b) => b.avg_change - a.avg_change);
    if (by === 'bear')  sorted.sort((a, b) => a.avg_change - b.avg_change);
    if (by === 'name')  sorted.sort((a, b) => a.sector.localeCompare(b.sector));
    if (by === 'ratio') sorted.sort((a, b) => b.up_pct - a.up_pct);
    _renderHeatmap(sorted);
}

// helper already in app.js: fmtVol
