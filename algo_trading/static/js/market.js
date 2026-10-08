/**
 * market.js - Gainers, Losers, All Stocks & Base Candle Breakout Screener
 */

let _allStocksCache     = [];   // Full list cache
let _allStocksSummary   = {};   // Summary counts cache
let _selectedStock      = null; // Currently selected stock for chart
let _currentChartTf     = 'D';  // Current chart timeframe: 'D', '15', '5', '1'
let _currentStatusFilter = 'all_triggers';
let _stocksAutoTimer    = null;
let _gainersLoaded      = false;

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

    if (data.plan_issue) {
        const msg = `<tr><td colspan="11" class="empty" style="color:var(--yellow);padding:24px">
            ⚠️ <b>Live Market Data Available Nahi</b><br><br>
            Aapki Kite app <b>"Personal"</b> type pe hai.<br>
            Live quotes ke liye <b>developers.kite.trade</b> pe jaao aur app type <b>"Connect"</b> karo.<br><br>
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
        : gainers.map((s, i) => stockRowStandard(s, i+1, 'gainer')).join('')
    );
    setHTML('losers-body', losers.length === 0
        ? '<tr><td colspan="11" class="empty">Koi losers nahi mila.</td></tr>'
        : losers.map((s, i) => stockRowStandard(s, i+1, 'loser')).join('')
    );
    _gainersLoaded = true;
}


// ─── ALL STOCKS & BASE CANDLE SCREENER ───────────────────────

function initStocksPage() {
    if (_allStocksCache.length === 0) {
        loadStocks();
    }
}

function setStocksFilter(filterName, btn) {
    _currentStatusFilter = filterName;
    document.querySelectorAll('#stocks-filter-pills .sc-pill').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadStocks();
}

function toggleStocksAutoRefresh() {
    const isAuto = document.getElementById('stocks-auto-refresh')?.checked;
    if (_stocksAutoTimer) {
        clearInterval(_stocksAutoTimer);
        _stocksAutoTimer = null;
    }
    if (isAuto) {
        _stocksAutoTimer = setInterval(() => {
            loadStocks(true); // silent refresh
        }, 10000);
        showToast('🔄 Auto-refresh enabled (10s)', 'toast-info');
    } else {
        showToast('⏸️ Auto-refresh disabled', 'toast-info');
    }
}

async function loadStocks(isSilent = false) {
    const universe     = document.getElementById('f-universe')?.value || 'fno';
    const maxBody      = parseFloat(document.getElementById('f-max-body')?.value || 50);
    const nearPct      = parseFloat(document.getElementById('f-near-pct')?.value || 0.6);
    const minPrice     = parseFloat(document.getElementById('f-min')?.value || 50);
    const maxPrice     = parseFloat(document.getElementById('f-max')?.value || 20000);
    const sortBy       = document.getElementById('f-sort')?.value || 'status_desc';
    const searchQ      = (document.getElementById('f-search')?.value || '').trim();
    const btnScan      = document.getElementById('stocks-scan-btn');

    if (btnScan && !isSilent) {
        btnScan.disabled = true;
        btnScan.innerHTML = '⏳ Scanning...';
    }

    const universeLabels = {
        fno: 'Universe: F&O (185)',
        nifty50: 'Universe: Nifty 50',
        nifty100: 'Universe: Nifty 100',
        nifty500: 'Universe: Nifty 500',
        all_stocks: 'Universe: All NSE EQ (~1,800+)',
        watchlist: 'Universe: My Watchlist',
    };
    setText('stocks-range-info', universeLabels[universe] || universe);

    if (!isSilent && _allStocksCache.length === 0) {
        setHTML('stocks-body', `<tr><td colspan="10" class="empty loading-msg">
            ⏳ Scanning previous day Base Candles & Breakouts... please wait
        </td></tr>`);
    }

    const baseOnly = (_currentStatusFilter !== 'all' && _currentStatusFilter !== 'all_stocks') ? 'true' : 'false';
    const url = `/api/market/stocks?universe=${encodeURIComponent(universe)}&status_filter=${encodeURIComponent(_currentStatusFilter)}&base_only=${baseOnly}&max_body=${maxBody}&near_pct=${nearPct}&min=${minPrice}&max=${maxPrice}&sort=${sortBy}&q=${encodeURIComponent(searchQ)}`;

    const data = await api(url);

    if (btnScan) {
        btnScan.disabled = false;
        btnScan.innerHTML = '⚡ Scan Now';
    }

    if (!data || !data.stocks) {
        if (!isSilent) {
            setHTML('stocks-body', '<tr><td colspan="10" class="empty red">❌ Data load nahi hua. Login check karo.</td></tr>');
        }
        return;
    }

    _allStocksCache   = data.stocks || [];
    _allStocksSummary = data.summary || {};

    // Update Counter Badges
    updateSummaryBadges(_allStocksSummary);

    setText('stocks-total', `${_allStocksCache.length} stocks`);

    renderStocksTable(_allStocksCache);

    // Auto-select first stock if none selected or selected not in current list
    if (_allStocksCache.length > 0) {
        if (!_selectedStock || !_allStocksCache.some(s => s.symbol === _selectedStock.symbol)) {
            selectStockForChart(_allStocksCache[0]);
        } else {
            // Update selected stock with fresh price data
            const fresh = _allStocksCache.find(s => s.symbol === _selectedStock.symbol);
            if (fresh) selectStockForChart(fresh, false); // don't reload iframe unnecessarily
        }
    }
}

function updateSummaryBadges(sum) {
    if (!sum) return;
    setText('cnt-all-triggers', sum.all_triggers_count || 0);
    setText('cnt-high-break',   sum.high_breakouts_count || 0);
    setText('cnt-near-high',    sum.near_high_count || 0);
    setText('cnt-low-break',    sum.low_breakdown_count || 0);
    setText('cnt-near-low',     sum.near_low_count || 0);
    setText('cnt-all-base',     sum.base_candles_count || 0);
    setText('cnt-all-stocks',   sum.all_stocks_count || 0);
}

function renderStocksTable(stocks) {
    if (!stocks || stocks.length === 0) {
        setHTML('stocks-body', `<tr><td colspan="10" class="empty" style="padding:28px">
            ℹ️ Koi stock nahi mila is filter me.<br>
            <span style="font-size:11px;color:var(--text3)">Try switching filter to "All Base Candles" ya Universe change karein.</span>
        </td></tr>`);
        return;
    }

    const rows = stocks.map((s, i) => {
        const isSelected = _selectedStock && _selectedStock.symbol === s.symbol;
        const selectedCls = isSelected ? 'selected-row' : '';

        // Status badge
        let statusBadge = '';
        if (s.status === 'HIGH_BREAKOUT') {
            statusBadge = `<span class="sc-badge-status badge-high-break">🔥 High Breakout</span>`;
        } else if (s.status === 'NEAR_HIGH') {
            statusBadge = `<span class="sc-badge-status badge-near-high">⚡ Near High Break</span>`;
        } else if (s.status === 'LOW_BREAKDOWN') {
            statusBadge = `<span class="sc-badge-status badge-low-break">🔻 Low Breakdown</span>`;
        } else if (s.status === 'NEAR_LOW') {
            statusBadge = `<span class="sc-badge-status badge-near-low">⚠️ Near Low Break</span>`;
        } else if (s.status === 'INSIDE_BASE') {
            statusBadge = `<span class="sc-badge-status badge-inside-base">📦 Inside Base</span>`;
        } else {
            statusBadge = `<span class="sc-badge-status badge-normal">Normal</span>`;
        }

        // Base Candle badge
        let baseBodyBadge = '';
        if (s.body_ratio_pct <= 20) {
            baseBodyBadge = `<span class="sc-body-pill doji" title="Doji / Very Narrow Base">${s.body_ratio_pct}% Doji</span>`;
        } else if (s.body_ratio_pct <= 35) {
            baseBodyBadge = `<span class="sc-body-pill tight" title="Tight Base Candle">${s.body_ratio_pct}% Tight</span>`;
        } else if (s.body_ratio_pct <= 50) {
            baseBodyBadge = `<span class="sc-body-pill standard" title="Base Consolidation">${s.body_ratio_pct}% Base</span>`;
        } else {
            baseBodyBadge = `<span class="sc-body-pill expansion" title="Trend/Expansion">${s.body_ratio_pct}% Wide</span>`;
        }

        // Change color
        const cc = s.change_pct > 0 ? 'green' : s.change_pct < 0 ? 'red' : 'dim';
        const sign = s.change_pct > 0 ? '+' : '';

        // Distance format
        let distHtml = '';
        if (s.status === 'HIGH_BREAKOUT') {
            distHtml = `<span class="green"><b>+${s.distance_pct.toFixed(2)}%</b> above PDH</span>`;
        } else if (s.status === 'NEAR_HIGH') {
            distHtml = `<span class="yellow"><b>${Math.abs(s.distance_pct).toFixed(2)}%</b> to PDH</span>`;
        } else if (s.status === 'LOW_BREAKDOWN') {
            distHtml = `<span class="red"><b>-${s.distance_pct.toFixed(2)}%</b> below PDL</span>`;
        } else if (s.status === 'NEAR_LOW') {
            distHtml = `<span class="orange"><b>${Math.abs(s.distance_pct).toFixed(2)}%</b> to PDL</span>`;
        } else {
            distHtml = `<span class="dim">${sign}${s.change_pct.toFixed(2)}%</span>`;
        }

        const fnoPill = s.is_fno ? `<span class="fno-tag" title="F&O Eligible">F&O</span>` : '';

        return `<tr class="screener-row ${selectedCls}" onclick="onStockRowClicked('${s.symbol}')" id="row-${s.symbol}">
            <td class="dim">${i + 1}</td>
            <td>
                <div style="display:flex;align-items:center;gap:5px">
                    <b>${s.symbol}</b>
                    ${fnoPill}
                </div>
                <div class="dim" style="font-size:10.5px;max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.name || ''}</div>
            </td>
            <td>${statusBadge}</td>
            <td><b>₹${s.ltp ? s.ltp.toFixed(2) : '--'}</b></td>
            <td class="${cc}"><b>${sign}${s.change_pct.toFixed(2)}%</b></td>
            <td class="green">₹${s.prev_high ? s.prev_high.toFixed(2) : '--'}</td>
            <td class="red">₹${s.prev_low ? s.prev_low.toFixed(2) : '--'}</td>
            <td>${baseBodyBadge}</td>
            <td>${distHtml}</td>
            <td>
                <div style="display:flex;gap:4px">
                    <button class="btn-sm btn-chart-action" onclick="event.stopPropagation();onStockRowClicked('${s.symbol}')" title="View Chart">📈</button>
                    <button class="btn-sm btn-add" onclick="event.stopPropagation();addToWatchlist('${s.symbol}')" title="Add to Watchlist">+</button>
                </div>
            </td>
        </tr>`;
    }).join('');

    setHTML('stocks-body', rows);
}

function onStockRowClicked(symbol) {
    const stock = _allStocksCache.find(s => s.symbol === symbol);
    if (stock) {
        selectStockForChart(stock, true);
    }
}

function selectStockForChart(stock, reloadIframe = true) {
    if (!stock) return;
    _selectedStock = stock;

    // Highlight row
    document.querySelectorAll('.screener-row').forEach(r => r.classList.remove('selected-row'));
    const activeRow = document.getElementById(`row-${stock.symbol}`);
    if (activeRow) activeRow.classList.add('selected-row');

    // Header info
    setText('chart-sym-badge', `NSE:${stock.symbol}`);
    setText('chart-sym-name', stock.name || stock.symbol);
    setText('chart-ltp', `₹${stock.ltp ? stock.ltp.toFixed(2) : '--'}`);

    const sign = stock.change_pct > 0 ? '+' : '';
    const cc = stock.change_pct > 0 ? 'green' : stock.change_pct < 0 ? 'red' : 'dim';
    const chgEl = document.getElementById('chart-chg');
    if (chgEl) {
        chgEl.textContent = `${sign}${stock.change_pct ? stock.change_pct.toFixed(2) : 0}%`;
        chgEl.className = `chart-chg ${cc}`;
    }

    // External TV link
    const extLink = document.getElementById('chart-external-link');
    if (extLink) {
        extLink.href = `https://in.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(stock.symbol)}`;
    }

    // Status & Levels Strip
    const lvlStatus = document.getElementById('chart-lvl-status');
    if (lvlStatus) {
        lvlStatus.textContent = stock.status_label || stock.status || '--';
        lvlStatus.className = `lvl-val ${cc}`;
    }

    setText('chart-lvl-pdh', stock.prev_high ? `₹${stock.prev_high.toFixed(2)}` : '--');
    setText('chart-lvl-pdl', stock.prev_low ? `₹${stock.prev_low.toFixed(2)}` : '--');
    setText('chart-lvl-body', `${stock.body_ratio_pct ? stock.body_ratio_pct.toFixed(1) : '--'}% (${stock.base_type || 'Base'})`);

    let distText = '--';
    if (stock.status === 'HIGH_BREAKOUT') {
        distText = `+${stock.distance_pct.toFixed(2)}% above PDH`;
    } else if (stock.status === 'NEAR_HIGH') {
        distText = `${Math.abs(stock.distance_pct).toFixed(2)}% to PDH`;
    } else if (stock.status === 'LOW_BREAKDOWN') {
        distText = `-${stock.distance_pct.toFixed(2)}% below PDL`;
    } else if (stock.status === 'NEAR_LOW') {
        distText = `${Math.abs(stock.distance_pct).toFixed(2)}% to PDL`;
    } else {
        distText = `${sign}${stock.change_pct.toFixed(2)}%`;
    }
    setText('chart-lvl-dist', distText);

    // Embed TradingView Chart
    if (reloadIframe) {
        embedTradingViewChart(stock.symbol, _currentChartTf);
    }
}

function changeChartTimeframe(tf, btn) {
    _currentChartTf = tf;
    document.querySelectorAll('.chart-tf-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    if (_selectedStock) {
        embedTradingViewChart(_selectedStock.symbol, tf);
    }
}

function embedTradingViewChart(symbol, interval = 'D') {
    const container = document.getElementById('stocks-chart-embed');
    if (!container) return;

    // TradingView embed widget iframe
    const sym = `NSE:${encodeURIComponent(symbol)}`;
    const tvUrl = `https://s.tradingview.com/widgetembed/?frameElementId=tradingview_stock_chart&symbol=${sym}&interval=${encodeURIComponent(interval)}&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=131722&studies=%5B%5D&theme=dark&style=1&timezone=Asia%2FKolkata&locale=en&utm_source=localhost`;

    container.innerHTML = `<iframe 
        id="tv-chart-frame"
        src="${tvUrl}" 
        style="width:100%;height:100%;border:none;border-radius:6px;"
        allowtransparency="true" 
        scrolling="no" 
        allowfullscreen>
    </iframe>`;
}

function quickTradeSelected(direction) {
    if (!_selectedStock) {
        showToast('Pehle koi stock select karein', 'toast-warning');
        return;
    }
    showPage('trade');
    setTimeout(() => {
        const symInput = document.getElementById('t-symbol');
        if (symInput) {
            symInput.value = _selectedStock.symbol;
            if (typeof fetchTradeQuote === 'function') fetchTradeQuote();
        }
        if (direction === 'BUY' && typeof selectTradeType === 'function') {
            selectTradeType('BUY');
        } else if (direction === 'SELL' && typeof selectTradeType === 'function') {
            selectTradeType('SELL');
        }
    }, 150);
}

function quickWatchlistSelected() {
    if (!_selectedStock) return;
    addToWatchlist(_selectedStock.symbol);
}

function filterStocksTable() {
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
    setText('stocks-total', `${filtered.length} stocks`);
}

// ─── STANDARD GAINERS / LOSERS ROW ───────────────────────────
function stockRowStandard(s, rank, type) {
    const chg    = s.change_pct || 0;
    const chgAmt = s.change     || 0;
    const cc     = chg > 0 ? 'green' : chg < 0 ? 'red' : 'dim';
    const arrow  = chg > 0 ? '▲' : chg < 0 ? '▼' : '─';
    const sign   = chg > 0 ? '+' : '';

    const ltpStr  = s.ltp > 0 ? '₹' + s.ltp.toFixed(2)  : '<span class="dim">--</span>';
    const volStr  = s.volume > 0 ? fmtVol(s.volume) : '--';
    const nameStr = (s.name || s.symbol).substring(0, 22);

    const chgStr  = s.ltp > 0
        ? `<span class="${cc}"><b>${arrow} ${sign}${chg.toFixed(2)}%</b></span>`
        : '<span class="dim">--</span>';

    const chgAmtStr = s.ltp > 0
        ? `<span class="${cc}">${sign}₹${Math.abs(chgAmt).toFixed(2)}</span>`
        : '<span class="dim">--</span>';

    const actionBtn = `<button class="btn-sm btn-add" onclick="addToWatchlist('${s.symbol}')">+ Watch</button>`;

    return `<tr>
        <td class="dim">${rank}</td>
        <td>
            <a href="https://in.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(s.symbol)}" target="_blank" rel="noopener noreferrer" class="tv-chart-link" title="Open ${s.symbol} chart on TradingView">
                <b>${s.symbol}</b><span class="tv-icon">↗</span>
            </a>
        </td>
        <td class="dim" style="max-width:140px;overflow:hidden;text-overflow:ellipsis" title="${s.name || ''}">
            ${nameStr}
        </td>
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

// ─── WATCHLIST ADD ───────────────────────────────────────────
async function addToWatchlist(symbol) {
    const res = await api('/api/watchlist/add', 'POST', { symbol });
    if (res?.success) {
        showToast(`✅ ${symbol} watchlist mein add hua!`, 'toast-success');
    } else {
        showToast(`ℹ️ ${symbol} already watchlist mein hai`, 'toast-info');
    }
}
