/**
 * market.js - Gainers, Losers, Stock Screener
 */

let _allStocksCache = [];   // Full list cache
let _gainersLoaded  = false;

// ─── GAINERS / LOSERS ────────────────────────────────────────
async function loadGainersLosers() {
    setHTML('gainers-body', '<tr><td colspan="11" class="empty loading-msg">⏳ Loading gainers...</td></tr>');
    setHTML('losers-body',  '<tr><td colspan="11" class="empty loading-msg">⏳ Loading losers...</td></tr>');

    const data = await api('/api/market/gainers-losers');
    if (!data) {
        const errMsg = '<tr><td colspan="11" class="empty">❌ Server se data nahi mila.</td></tr>';
        setHTML('gainers-body', errMsg);
        setHTML('losers-body',  errMsg);
        return;
    }

    // Plan issue - Personal plan pe live data nahi milta
    if (data.plan_issue) {
        const msg = `<tr><td colspan="11" class="empty" style="color:var(--yellow);padding:24px">
            ⚠️ <b>Live Market Data Available Nahi</b><br><br>
            Aapki Kite app <b>"Personal"</b> type pe hai.<br>
            Live quotes ke liye <b>developers.kite.trade</b> pe jaao aur app type<br>
            <b>"Connect"</b> karo (500 credits/30 days).<br><br>
            <span style="color:var(--text3);font-size:11px">Personal plan mein historical data aur live quotes nahi milti.</span>
        </td></tr>`;
        setHTML('gainers-body', msg);
        setHTML('losers-body',  msg);
        return;
    }

    if (data.error && !data.gainers?.length) {
        const errMsg = `<tr><td colspan="11" class="empty red">${data.error}</td></tr>`;
        setHTML('gainers-body', errMsg);
        setHTML('losers-body',  errMsg);
        return;
    }

    const gainers = data.gainers || [];
    const losers  = data.losers  || [];

    setText('gainers-count', gainers.length);
    setText('losers-count',  losers.length);
    setText('gainers-total', gainers.length + ' stocks');
    setText('losers-total',  losers.length  + ' stocks');

    setHTML('gainers-body', gainers.length === 0
        ? '<tr><td colspan="11" class="empty">Koi gainers nahi mila. Market open hai?</td></tr>'
        : gainers.map((s, i) => stockRow(s, i+1, 'gainer')).join('')
    );
    setHTML('losers-body', losers.length === 0
        ? '<tr><td colspan="11" class="empty">Koi losers nahi mila.</td></tr>'
        : losers.map((s, i) => stockRow(s, i+1, 'loser')).join('')
    );
    _gainersLoaded = true;
}

// ─── ALL STOCKS ──────────────────────────────────────────────
async function loadStocks() {
    const minPrice = parseFloat(document.getElementById('f-min')?.value  || 50);
    const maxPrice = parseFloat(document.getElementById('f-max')?.value  || 20000);
    const sortBy   = document.getElementById('f-sort')?.value  || 'chg_desc';
    const searchQ  = (document.getElementById('f-search')?.value || '').trim();

    setText('stocks-range-info', `Price: ₹${minPrice} - ₹${maxPrice.toLocaleString('en-IN')}`);
    setHTML('stocks-body', `<tr><td colspan="12" class="empty loading-msg">
        ⏳ Loading stocks... thoda wait karo
    </td></tr>`);

    const url  = `/api/market/stocks?min=${minPrice}&max=${maxPrice}&sort=${sortBy}&q=${encodeURIComponent(searchQ)}`;
    const data = await api(url);

    if (!data || !data.stocks) {
        setHTML('stocks-body', '<tr><td colspan="12" class="empty red">❌ Data load nahi hua.</td></tr>');
        return;
    }

    _allStocksCache  = data.stocks;
    const hasLive    = data.has_live_data;

    setText('stocks-total', data.total + ' stocks');
    setText('stocks-count', data.total);

    // Warning agar no live data
    if (!hasLive) {
        showToast('⚠️ Live prices unavailable - sirf symbol list dikh rahi hai (Personal plan limitation)', 'toast-info');
    }

    renderStocksTable(_allStocksCache, hasLive);
}

function renderStocksTable(stocks, hasLive = true) {
    if (stocks.length === 0) {
        setHTML('stocks-body', '<tr><td colspan="12" class="empty">Koi stock nahi mila is range mein</td></tr>');
        return;
    }
    setHTML('stocks-body', stocks.map((s, i) => stockRow(s, i+1, 'stock', hasLive)).join(''));
    setText('stocks-total', stocks.length + ' stocks');
}

function filterStocksTable() {
    // Local filter on cached data
    const q = (document.getElementById('f-search')?.value || '').toUpperCase().trim();
    if (!q) {
        renderStocksTable(_allStocksCache);
        return;
    }
    const filtered = _allStocksCache.filter(s =>
        s.symbol.toUpperCase().includes(q) ||
        (s.name || '').toUpperCase().includes(q)
    );
    renderStocksTable(filtered);
    setText('stocks-total', filtered.length + ' stocks');
}

// ─── ROW BUILDER ─────────────────────────────────────────────
function stockRow(s, rank, type, hasLive = true) {
    const chg    = s.change_pct || 0;
    const chgAmt = s.change     || 0;
    const cc     = chg > 0 ? 'green' : chg < 0 ? 'red' : 'dim';
    const arrow  = chg > 0 ? '▲' : chg < 0 ? '▼' : '─';
    const sign   = chg > 0 ? '+' : '';

    const ltpStr  = s.ltp  > 0 ? '₹' + s.ltp.toFixed(2)  : '<span class="dim">--</span>';
    const volStr  = s.volume > 0 ? fmtVol(s.volume) : '--';
    const nameStr = (s.name || s.symbol).substring(0, 22);

    const chgStr  = s.ltp > 0
        ? `<span class="${cc}"><b>${arrow} ${sign}${chg.toFixed(2)}%</b></span>`
        : '<span class="dim">--</span>';

    const chgAmtStr = s.ltp > 0
        ? `<span class="${cc}">${sign}₹${Math.abs(chgAmt).toFixed(2)}</span>`
        : '<span class="dim">--</span>';

    const actionBtn = `<button class="btn-sm btn-add" onclick="addToWatchlist('${s.symbol}')">+ Watch</button>`;

    if (type === 'stock') {
        return `<tr>
            <td class="dim">${rank}</td>
            <td><b>${s.symbol}</b></td>
            <td class="dim" style="max-width:140px;overflow:hidden;text-overflow:ellipsis" title="${s.name || ''}">${nameStr}</td>
            <td class="dim">${s.prev_close > 0 ? '₹'+s.prev_close.toFixed(2) : '--'}</td>
            <td><b>${ltpStr}</b></td>
            <td>${chgAmtStr}</td>
            <td>${chgStr}</td>
            <td class="dim">${s.open  > 0 ? '₹'+s.open.toFixed(2)  : '--'}</td>
            <td class="green">${s.high > 0 ? '₹'+s.high.toFixed(2) : '--'}</td>
            <td class="red">${s.low   > 0 ? '₹'+s.low.toFixed(2)   : '--'}</td>
            <td class="dim">${volStr}</td>
            <td>${actionBtn}</td>
        </tr>`;
    } else {
        return `<tr>
            <td class="dim">${rank}</td>
            <td><b>${s.symbol}</b></td>
            <td class="dim" style="max-width:140px;overflow:hidden;text-overflow:ellipsis" title="${s.name || ''}">${nameStr}</td>
            <td><b>${ltpStr}</b></td>
            <td>${chgAmtStr}</td>
            <td>${chgStr}</td>
            <td class="dim">${s.open  > 0 ? '₹'+s.open.toFixed(2)  : '--'}</td>
            <td class="green">${s.high > 0 ? '₹'+s.high.toFixed(2) : '--'}</td>
            <td class="red">${s.low   > 0 ? '₹'+s.low.toFixed(2)   : '--'}</td>
            <td class="dim">${volStr}</td>
            <td>${actionBtn}</td>
        </tr>`;
    }
}

// ─── WATCHLIST ADD ───────────────────────────────────────────
async function addToWatchlist(symbol) {
    const res = await api('/api/watchlist/add', 'POST', { symbol });
    if (res?.success) {
        showToast(`✅ ${symbol} watchlist mein add hua!`, 'toast-success');
    } else {
        showToast(`ℹ️ ${symbol} already watchlist mein hai`, 'toast-info');
    }
}
