/**
 * market.js - Gainers, Losers, All Stocks & Base Candle Breakout Screener
 * Features:
 *  - Previous Day Base Candle Detection (Body <= 50% Range)
 *  - Live PDH/PDL Breakout & Near Breakout Tracking
 *  - 100% Custom Native HTML5 Candlestick Chart with PDH/PDL Lines & Base Box Overlay
 */

let _allStocksCache      = [];   // Full list cache
let _allStocksSummary    = {};   // Summary counts cache
let _selectedStock       = null; // Currently selected stock for chart
let _currentChartTf      = 'day';// Timeframe: 'day', '15minute', '5minute', 'minute'
let _currentStatusFilter = 'all_triggers';
let _stocksAutoTimer     = null;
let _gainersLoaded       = false;

// Custom Chart Interactive State
let _chartCandlesData    = [];
let _chartPrevDayData    = {};
let _chartHoverIndex     = -1;
let _chartMousePos       = null;
let _chartCanvasElem     = null;
let _chartVisibleCount   = 45;   // number of visible candles on screen
let _chartOffset         = 0;    // scroll offset from end
let _isChartDragging     = false;
let _chartDragStartX     = 0;
let _chartDragStartOffset = 0;

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
            const fresh = _allStocksCache.find(s => s.symbol === _selectedStock.symbol);
            if (fresh) selectStockForChart(fresh, false);
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

        const cc = s.change_pct > 0 ? 'green' : s.change_pct < 0 ? 'red' : 'dim';
        const sign = s.change_pct > 0 ? '+' : '';

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

function selectStockForChart(stock, reloadChart = true) {
    if (!stock) return;
    _selectedStock = stock;

    // Highlight active row in table
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

    // Render Custom Canvas Candlestick Chart
    if (reloadChart) {
        _chartOffset = 0;
        loadCustomCandleChart(stock.symbol, _currentChartTf);
    }
}

function changeChartTimeframe(tf, btn) {
    // Map button key to API interval
    const tfMap = {
        'D': 'day',
        '15': '15minute',
        '5': '5minute',
        '1': 'minute',
    };
    _currentChartTf = tfMap[tf] || tf;

    document.querySelectorAll('.chart-tf-group .chart-tf-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    if (_selectedStock) {
        _chartOffset = 0;
        loadCustomCandleChart(_selectedStock.symbol, _currentChartTf);
    }
}


// ═══════════════════════════════════════════════════════════════
// 🌟 100% INDEPENDENT CUSTOM HTML5 CANDLESTICK CHART ENGINE
// ═══════════════════════════════════════════════════════════════

async function loadCustomCandleChart(symbol, interval = 'day') {
    const container = document.getElementById('stocks-chart-embed');
    if (!container) return;

    container.innerHTML = `
        <div class="custom-chart-wrapper">
            <div class="custom-chart-infobar" id="custom-chart-infobar">
                <span class="cc-info-sym"><b>${symbol}</b> (${interval.toUpperCase()})</span>
                <span class="cc-info-val" id="cc-hover-data">⏳ Loading live candlestick data...</span>
            </div>
            <div class="custom-chart-canvas-box" id="cc-canvas-box">
                <canvas id="custom-candle-canvas"></canvas>
            </div>
            <div class="custom-chart-legend">
                <span class="c-leg-item"><span class="c-leg-line cyan-solid"></span> Live Price (LTP)</span>
                <span class="c-leg-hint">🖱️ Drag to pan • Scroll to zoom</span>
            </div>
        </div>
    `;

    const res = await api(`/api/chart/candles?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`);
    if (!res || !res.candles || res.candles.length === 0) {
        const infobar = document.getElementById('cc-hover-data');
        if (infobar) infobar.innerHTML = `<span class="red">⚠️ No candlestick history returned from Kite API</span>`;
        return;
    }

    _chartCandlesData = res.candles || [];
    _chartPrevDayData = res.prev_day || {};

    initCustomCanvasEvents();
    drawCustomChart();
}

function initCustomCanvasEvents() {
    const canvas = document.getElementById('custom-candle-canvas');
    if (!canvas) return;
    _chartCanvasElem = canvas;

    // Mouse Move (Crosshair & Tooltip)
    canvas.onmousemove = (e) => {
        const rect = canvas.getBoundingClientRect();
        _chartMousePos = {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
        };

        if (_isChartDragging) {
            const deltaX = e.clientX - _chartDragStartX;
            const candlesMoved = Math.round(deltaX / (canvas.clientWidth / _chartVisibleCount));
            _chartOffset = Math.max(0, Math.min(_chartCandlesData.length - _chartVisibleCount, _chartDragStartOffset + candlesMoved));
        }

        drawCustomChart();
    };

    // Mouse Leave
    canvas.onmouseleave = () => {
        _chartMousePos = null;
        _chartHoverIndex = -1;
        _isChartDragging = false;
        drawCustomChart();
    };

    // Mouse Down (Pan drag)
    canvas.onmousedown = (e) => {
        _isChartDragging = true;
        _chartDragStartX = e.clientX;
        _chartDragStartOffset = _chartOffset;
    };

    // Mouse Up
    window.onmouseup = () => {
        _isChartDragging = false;
    };

    // Mouse Wheel (Zoom in / out)
    canvas.onwheel = (e) => {
        e.preventDefault();
        if (e.deltaY < 0) {
            // Zoom in
            _chartVisibleCount = Math.max(15, _chartVisibleCount - 4);
        } else {
            // Zoom out
            _chartVisibleCount = Math.min(Math.min(120, _chartCandlesData.length), _chartVisibleCount + 4);
        }
        drawCustomChart();
    };

    // Resize Observer
    const resizeObserver = new ResizeObserver(() => {
        drawCustomChart();
    });
    const box = document.getElementById('cc-canvas-box');
    if (box) resizeObserver.observe(box);
}

function drawCustomChart() {
    const canvas = document.getElementById('custom-candle-canvas');
    if (!canvas || !_chartCandlesData || _chartCandlesData.length === 0) return;

    const ctx = canvas.getContext('2d');
    const box = canvas.parentElement;
    const width = box.clientWidth || 400;
    const height = box.clientHeight || 450;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';

    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    // Padding configuration
    const padTop = 20;
    const padBottom = 30;
    const padRight = 65; // Price scale
    const padLeft = 10;
    const volHeight = Math.max(50, height * 0.16);
    const mainHeight = height - padTop - padBottom - volHeight;

    // Slice visible window
    const totalCandles = _chartCandlesData.length;
    const count = Math.min(totalCandles, _chartVisibleCount);
    const endIndex = Math.max(count, totalCandles - _chartOffset);
    const startIndex = Math.max(0, endIndex - count);
    const visibleData = _chartCandlesData.slice(startIndex, endIndex);

    if (visibleData.length === 0) return;

    // Determine min & max price
    let minPrice = Infinity;
    let maxPrice = -Infinity;
    let maxVol   = 0;
    visibleData.forEach(c => {
        if (c.low < minPrice) minPrice = c.low;
        if (c.high > maxPrice) maxPrice = c.high;
        if (c.volume > maxVol) maxVol = c.volume;
    });

    const ltp = _selectedStock ? _selectedStock.ltp : 0;

    if (ltp > 0) {
        maxPrice = Math.max(maxPrice, ltp);
        minPrice = Math.min(minPrice, ltp);
    }

    // Add 4% vertical padding
    const pMargin = (maxPrice - minPrice) * 0.04 || 1;
    maxPrice += pMargin;
    minPrice -= pMargin;
    const priceRange = maxPrice - minPrice || 1;

    // Coordinate mapping functions
    const chartW = width - padLeft - padRight;
    const candleW = chartW / visibleData.length;
    const bodyW = Math.max(2, candleW * 0.72);

    const getY = (price) => padTop + (1 - (price - minPrice) / priceRange) * mainHeight;
    const getX = (idx) => padLeft + (idx + 0.5) * candleW;

    // ── 1. Draw Background Grid & Price Labels ──
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#64748b';
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';

    const gridSteps = 6;
    for (let i = 0; i <= gridSteps; i++) {
        const p = minPrice + (i / gridSteps) * priceRange;
        const y = getY(p);

        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(width - padRight, y);
        ctx.stroke();

        ctx.fillText('₹' + p.toFixed(2), width - padRight + 6, y + 3);
    }

    // ── 2. Draw Volume Bars ──
    const volTop = padTop + mainHeight + 8;
    visibleData.forEach((c, idx) => {
        const x = getX(idx);
        const isBull = c.close >= c.open;
        const vH = maxVol > 0 ? (c.volume / maxVol) * (volHeight - 12) : 0;
        const vY = volTop + (volHeight - 12) - vH;

        ctx.fillStyle = isBull ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)';
        ctx.fillRect(x - bodyW / 2, vY, bodyW, vH);
    });

    // ── 5. Draw Candlesticks ──
    visibleData.forEach((c, idx) => {
        const x = getX(idx);
        const yOpen = getY(c.open);
        const yClose = getY(c.close);
        const yHigh = getY(c.high);
        const yLow = getY(c.low);

        const isBull = c.close >= c.open;
        const color = isBull ? '#10b981' : '#ef4444';

        // Draw Wick (High to Low line)
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        // Draw Candle Body
        const topY = Math.min(yOpen, yClose);
        const bodyH = Math.max(2, Math.abs(yClose - yOpen));

        ctx.fillStyle = color;
        ctx.fillRect(x - bodyW / 2, topY, bodyW, bodyH);
    });

    // ── 6. Draw Current LTP Line ──
    if (ltp > 0) {
        const yLtp = getY(ltp);
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.2;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(padLeft, yLtp);
        ctx.lineTo(width - padRight, yLtp);
        ctx.stroke();
        ctx.setLineDash([]);

        // Live LTP Pulse badge on axis
        ctx.fillStyle = '#38bdf8';
        ctx.fillRect(width - padRight + 2, yLtp - 9, padRight - 4, 18);
        ctx.fillStyle = '#0f172a';
        ctx.font = 'bold 10px monospace';
        ctx.fillText('₹' + ltp.toFixed(2), width - padRight + 5, yLtp + 3.5);
    }

    // ── 7. Crosshair & Hover Tooltip ──
    let hoverCandle = null;
    if (_chartMousePos && _chartMousePos.x >= padLeft && _chartMousePos.x <= width - padRight) {
        const relX = _chartMousePos.x - padLeft;
        const hoverIdx = Math.min(visibleData.length - 1, Math.max(0, Math.floor(relX / candleW)));
        hoverCandle = visibleData[hoverIdx];
        const hX = getX(hoverIdx);
        const hY = _chartMousePos.y;

        // Vertical crosshair
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hX, padTop);
        ctx.lineTo(hX, height - padBottom);
        ctx.stroke();

        // Horizontal crosshair
        ctx.beginPath();
        ctx.moveTo(padLeft, hY);
        ctx.lineTo(width - padRight, hY);
        ctx.stroke();
        ctx.setLineDash([]);

        // Date pill on bottom axis
        if (hoverCandle) {
            const timeStr = hoverCandle.time.substring(5);
            ctx.fillStyle = '#3b82f6';
            ctx.fillRect(hX - 35, height - padBottom + 4, 70, 16);
            ctx.fillStyle = '#ffffff';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(timeStr, hX, height - padBottom + 16);
            ctx.textAlign = 'left';
        }
    }

    // Update Top Info Bar
    const targetCandle = hoverCandle || visibleData[visibleData.length - 1];
    if (targetCandle) {
        const infobar = document.getElementById('cc-hover-data');
        if (infobar) {
            const chg = targetCandle.close - targetCandle.open;
            const chgPct = targetCandle.open > 0 ? (chg / targetCandle.open * 100) : 0;
            const cc = chg >= 0 ? '#34d399' : '#f87171';
            const sign = chg >= 0 ? '+' : '';

            infobar.innerHTML = `
                <span><b>Time:</b> ${targetCandle.time}</span> |
                <span><b>O:</b> ₹${targetCandle.open.toFixed(2)}</span> |
                <span><b>H:</b> ₹${targetCandle.high.toFixed(2)}</span> |
                <span><b>L:</b> ₹${targetCandle.low.toFixed(2)}</span> |
                <span><b>C:</b> ₹${targetCandle.close.toFixed(2)}</span> |
                <span style="color:${cc}"><b>${sign}${chgPct.toFixed(2)}%</b></span> |
                <span><b>Vol:</b> ${fmtVol(targetCandle.volume)}</span>
            `;
        }
    }
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
