/**
 * scanner.js - Stock Scanner Frontend Logic
 * Updated: Index/Sector universe support
 */

let _scanResults   = [];
let _scanPollTimer = null;
let _activeFilter  = 'all';

// ─── INIT ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Custom symbols row toggle
    const uniSel = document.getElementById('sc-universe');
    if (uniSel) {
        uniSel.addEventListener('change', onUniverseChange);
        onUniverseChange();
    }
});

function onUniverseChange() {
    const val    = document.getElementById('sc-universe')?.value || '';
    const custom = document.getElementById('sc-custom-row');
    if (custom) custom.style.display = val === 'custom' ? 'flex' : 'none';

    // Show stock count hint with warnings for large scans
    const hints = {
        all_stocks:        '~1,800+ stocks (All NSE EQ, streaming)',
        all_nse:           '~1,800+ stocks (All NSE EQ, streaming)',
        nifty500:          '~500 stocks (streaming)',
        all_sectors:       '~200 stocks',
        nifty50:           '~50 stocks',
        nifty_next50:      '~50 stocks',
        nifty100:          '~100 stocks',
        nifty200:          '~200 stocks',
        nifty_midcap50:    '~50 stocks',
        nifty_midcap150:   '~65 stocks',
        nifty_smallcap100: '~80 stocks',
        banknifty:         '~15 stocks',
        finnifty:          '~20 stocks',
        sensex30:          '~30 stocks',
        bse100:            '~97 stocks',
        watchlist:         'your watchlist',
        custom:            'enter symbols below',
    };
    const hint = hints[val] || 'custom';
    const universeHint = document.getElementById('sc-universe-hint');
    if (universeHint) {
        universeHint.textContent = `(${hint})`;
        universeHint.style.color = (val === 'all_stocks' || val === 'all_nse' || val === 'nifty500') ? 'var(--yellow)' : 'var(--text3)';
    }
    
    const btn = document.getElementById('sc-run-btn');
    if (btn) btn.title = `Scan ${hint}`;
}

// ─── RUN SCANNER ─────────────────────────────────────────────
async function runScanner() {
    const universe  = document.getElementById('sc-universe')?.value  || 'nifty50';
    const timeframe = document.getElementById('sc-timeframe')?.value || 'day';
    const direction = document.getElementById('sc-direction')?.value || 'both';
    const minScore  = document.getElementById('sc-minscore')?.value  || '6';

    let symbols = universe;
    if (universe === 'custom') {
        const custom = (document.getElementById('sc-custom-syms')?.value || '').trim();
        if (!custom) { showToast('Custom symbols daalo! (comma separated)', 'toast-error'); return; }
        symbols = custom;
    }

    // Reset badge
    const badge = document.getElementById('scanner-badge');
    if (badge) badge.textContent = '...';

    const res = await api('/api/scanner/run', 'POST', {
        symbols:   symbols,
        timeframe: timeframe,
        direction: direction,
        min_score: parseInt(minScore),
    });

    if (!res?.success) {
        showToast(res?.error || 'Scanner start nahi hua', 'toast-error');
        return;
    }

    // Show progress UI
    _setDisplay('sc-run-btn',       'none');
    _setDisplay('sc-stop-btn',      'inline-flex');
    _setDisplay('sc-progress-wrap', 'flex');
    _setDisplay('sc-summary',       'none');
    _setDisplay('sc-filter-bar',    'none');
    setHTML('sc-results-grid',
        `<div class="sc-scanning-msg">
            <div style="font-size:32px;margin-bottom:10px">🔬</div>
            <b>Scanning ${res.total} stocks...</b><br>
            <span style="color:var(--text3);font-size:12px">
                Har stock ke indicators calculate ho rahe hain
            </span>
        </div>`);

    showToast(`🔬 Scanning ${res.total} stocks on ${timeframe}...`, 'toast-info');
    _startPolling();
}

async function stopScanner() {
    _stopPolling();
    try {
        await api('/api/scanner/cancel', 'POST');
    } catch (e) {}
    _setDisplay('sc-run-btn',       'inline-flex');
    _setDisplay('sc-stop-btn',      'none');
    _setDisplay('sc-progress-wrap', 'none');
    showToast('Scanner stopped', 'toast-info');
}

// ─── POLLING (Chunked Streaming Results) ────────────────────
let _lastResultCount = 0;

function _startPolling() {
    _lastResultCount = 0;  // Reset counter
    _scanPollTimer = setInterval(_pollStatus, 1500);
}

function _stopPolling() {
    if (_scanPollTimer) { clearInterval(_scanPollTimer); _scanPollTimer = null; }
}

async function _pollStatus() {
    const st = await api('/api/scanner/status');
    if (!st) return;

    // Update progress bar
    const fill = document.getElementById('sc-progress-fill');
    const txt  = document.getElementById('sc-progress-text');
    const cnt  = document.getElementById('sc-progress-count');
    const sym  = document.getElementById('sc-progress-sym');
    
    if (fill) fill.style.width  = st.pct + '%';
    if (txt)  txt.textContent   = `${st.pct}%`;
    if (cnt)  cnt.textContent   = `${st.progress}/${st.total}`;
    if (sym)  sym.textContent   = st.current ? `→ ${st.current}` : '';

    // CHUNKED STREAMING: Update results incrementally as they arrive
    if (st.results && st.results.length > _lastResultCount) {
        _scanResults = st.results;
        _lastResultCount = st.results.length;
        
        // Progressive UI update - show results even while scanning
        _renderResults(_scanResults);
        
        // Update badge in real-time
        const badge = document.getElementById('scanner-badge');
        if (badge) badge.textContent = _scanResults.length;

        // Update counts in summary bar
        const longs  = _scanResults.filter(r => r.direction === 'LONG').length;
        const shorts = _scanResults.filter(r => r.direction === 'SHORT').length;
        const strong = _scanResults.filter(r => r.score >= 8).length;
        setText('sc-long-count',    longs);
        setText('sc-short-count',   shorts);
        setText('sc-strong-count',  strong);
        setText('sc-scanned-count', st.progress);
        setText('sc-result-count',  _scanResults.length + ' signals');

        _setDisplay('sc-summary',    'flex');
        _setDisplay('sc-filter-bar', 'flex');
    }

    if (!st.running) {
        _stopPolling();
        _setDisplay('sc-run-btn',       'inline-flex');
        _setDisplay('sc-stop-btn',      'none');
        _setDisplay('sc-progress-wrap', 'none');

        if (st.error) {
            showToast('❌ ' + st.error, 'toast-error');
            setHTML('sc-results-grid',
                `<div class="sc-no-result">
                    <div style="font-size:36px">❌</div>
                    <b>Scan failed</b><br>
                    <span style="color:var(--text3)">${st.error}</span>
                </div>`);
            return;
        }

        _scanResults = st.results || [];
        _renderResults(_scanResults);

        // Update badge
        const badge = document.getElementById('scanner-badge');
        if (badge) badge.textContent = _scanResults.length;
        setText('sc-last-scan', st.last_scan ? `Last: ${st.last_scan}` : '');

        // Summary counts
        const longs  = _scanResults.filter(r => r.direction === 'LONG').length;
        const shorts = _scanResults.filter(r => r.direction === 'SHORT').length;
        const strong = _scanResults.filter(r => r.score >= 8).length;
        setText('sc-long-count',    longs);
        setText('sc-short-count',   shorts);
        setText('sc-strong-count',  strong);
        setText('sc-scanned-count', st.total);
        setText('sc-result-count',  _scanResults.length + ' signals');

        _setDisplay('sc-summary',    _scanResults.length > 0 ? 'flex' : 'none');
        _setDisplay('sc-filter-bar', _scanResults.length > 0 ? 'flex' : 'none');

        if (_scanResults.length > 0) {
            showToast(`✅ ${_scanResults.length} trade signals mile! (${longs} Long, ${shorts} Short)`, 'toast-success');
        } else {
            showToast('😐 Koi strong signal nahi mila. Min score kam karo ya alag timeframe try karo.', 'toast-info');
        }
    }
}

// ─── FILTER ──────────────────────────────────────────────────
function filterResults(type) {
    _activeFilter = type;
    document.querySelectorAll('.sc-filter-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.f === type));

    const q = (document.getElementById('sc-filter-search')?.value || '').toUpperCase().trim();
    let filtered = [..._scanResults];

    if (type === 'long')   filtered = filtered.filter(r => r.direction === 'LONG');
    if (type === 'short')  filtered = filtered.filter(r => r.direction === 'SHORT');
    if (type === 'strong') filtered = filtered.filter(r => r.score >= 8);
    if (type === 'rr3')    filtered = filtered.filter(r => r.rr_ratio >= 3);
    if (q || type === 'search') {
        filtered = filtered.filter(r =>
            r.symbol.includes(q) || (r.name || '').toUpperCase().includes(q));
    }

    _renderResults(filtered);
    setText('sc-result-count', filtered.length + ' signals');
}

// ─── RENDER ──────────────────────────────────────────────────
function _renderResults(results) {
    const grid = document.getElementById('sc-results-grid');
    if (!grid) return;

    if (!results.length) {
        grid.innerHTML = `
            <div class="sc-no-result">
                <div style="font-size:40px;margin-bottom:12px">🔍</div>
                <b>Koi signal nahi mila</b>
                <p style="color:var(--text3);font-size:12px;margin-top:8px">
                    Filter change karo ya min score kam karo
                </p>
            </div>`;
        return;
    }
    grid.innerHTML = results.map(r => signalCard(r)).join('');
}

// ─── SIGNAL CARD ─────────────────────────────────────────────
function signalCard(r) {
    const isLong  = r.direction === 'LONG';
    const dirCls  = isLong ? 'long' : 'short';
    const dirIcon = isLong ? '📈' : '📉';
    const sigCls  = r.signal_type?.includes('STRONG') ? 'signal-strong' : 'signal-normal';
    const confCls = r.confidence?.includes('HIGH') ? 'conf-high' : 'conf-med';

    const scorePct = Math.round((r.score / 10) * 100);
    const scoreCol = r.score >= 8 ? 'var(--green)' : r.score >= 6 ? 'var(--blue)' : 'var(--yellow)';
    const rrCol    = r.rr_ratio >= 3 ? 'var(--green)' : r.rr_ratio >= 2 ? 'var(--blue)' : 'var(--yellow)';
    const riskAmt  = Math.abs(r.entry - r.stop_loss).toFixed(2);

    return `
<div class="sc-card ${dirCls}">
    <div class="sc-card-head">
        <div class="sc-card-left">
            <a href="https://in.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(r.symbol)}" target="_blank" rel="noopener noreferrer" class="tv-chart-link" title="Open ${r.symbol} chart on TradingView (New Tab)">
                <span class="sc-symbol">${r.symbol}</span><span class="tv-icon">↗</span>
            </a>
            <a href="https://in.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(r.symbol)}" target="_blank" rel="noopener noreferrer" class="tv-name-link" title="Open ${r.symbol} chart on TradingView (New Tab)">
                <span class="sc-name">${(r.name || '').substring(0,20)}</span>
            </a>
        </div>
        <div class="sc-card-right">
            <span class="sc-dir-badge ${dirCls}">${dirIcon} ${r.direction}</span>
            <span class="sc-sig-badge ${sigCls}">${r.signal_type}</span>
        </div>
    </div>

    <div class="sc-score-row">
        <span class="sc-score-lbl">Score</span>
        <div class="sc-score-bar-wrap">
            <div class="sc-score-bar" style="width:${scorePct}%;background:${scoreCol}"></div>
        </div>
        <span class="sc-score-val" style="color:${scoreCol}">${r.score}/10</span>
        <span class="sc-conf ${confCls}">${r.confidence}</span>
    </div>

    <div class="sc-levels">
        <div class="sc-level-item">
            <div class="sc-level-lbl">LTP</div>
            <div class="sc-level-val">₹${r.ltp?.toFixed(2)}</div>
        </div>
        <div class="sc-level-item">
            <div class="sc-level-lbl">⚡ Entry</div>
            <div class="sc-level-val green">₹${r.entry?.toFixed(2)}</div>
        </div>
        <div class="sc-level-item">
            <div class="sc-level-lbl">🛑 Stop Loss</div>
            <div class="sc-level-val red">₹${r.stop_loss?.toFixed(2)}</div>
            <div class="sc-level-sub red">-${r.risk_pct?.toFixed(1)}%</div>
        </div>
        <div class="sc-level-item">
            <div class="sc-level-lbl">🎯 Target 1</div>
            <div class="sc-level-val" style="color:#fbbf24">₹${r.target1?.toFixed(2)}</div>
            <div class="sc-level-sub dim">1:1.5</div>
        </div>
        <div class="sc-level-item">
            <div class="sc-level-lbl">🎯 Target 2</div>
            <div class="sc-level-val" style="color:#34d399">₹${r.target2?.toFixed(2)}</div>
            <div class="sc-level-sub dim">1:2</div>
        </div>
        <div class="sc-level-item">
            <div class="sc-level-lbl">🎯 Target 3</div>
            <div class="sc-level-val green">₹${r.target3?.toFixed(2)}</div>
            <div class="sc-level-sub green">1:3</div>
        </div>
    </div>

    <div class="sc-rr-banner" style="border-color:${rrCol}30;background:${rrCol}10">
        <span style="color:${rrCol};font-weight:700;font-size:13px">
            Best R:R = ${r.best_rr}
        </span>
        <span class="dim" style="font-size:11px">Risk: ₹${riskAmt}/share</span>
        <span class="dim" style="font-size:11px">ATR: ₹${r.atr?.toFixed(2)}</span>
    </div>

    <div class="sc-pills">${_indicatorPills(r)}</div>

    <div class="sc-reasons">
        ${(r.reasons || []).slice(0,4).map(rs =>
            `<div class="sc-reason">${rs}</div>`).join('')}
        ${(r.warnings || []).slice(0,2).map(w =>
            `<div class="sc-warn">${w}</div>`).join('')}
    </div>

    <div class="sc-card-footer">
        <span class="sc-tf-tag">${r.timeframe}</span>
        <div class="sc-footer-actions">
            <button class="btn-sm btn-add" onclick="addToWatchlist('${r.symbol}')">+ Watch</button>
            <button class="btn-sm sc-buy-btn"
                onclick="event.stopPropagation();quickOrder('${r.symbol}','BUY',${r.entry},${r.stop_loss},${r.target1},${r.target2},${r.target3})">
                📈 BUY
            </button>
            <button class="btn-sm sc-sell-btn"
                onclick="event.stopPropagation();quickOrder('${r.symbol}','SELL',${r.entry},${r.stop_loss},${r.target1},${r.target2},${r.target3})">
                📉 SELL
            </button>
        </div>
    </div>
</div>`;
}

function _indicatorPills(r) {
    const isLong = r.direction === 'LONG';
    return [
        { label: `RSI ${r.rsi?.toFixed(0)}`,        ok: isLong ? (r.rsi>=40&&r.rsi<=70) : (r.rsi>=30&&r.rsi<=60) },
        { label: `MACD ${r.macd>r.macd_signal?'▲':'▼'}`,  ok: isLong ? r.macd>r.macd_signal : r.macd<r.macd_signal },
        { label: `ST ${r.supertrend_bull?'🟢':'🔴'}`,      ok: isLong ? r.supertrend_bull : !r.supertrend_bull },
        { label: `VWAP ${r.ltp>r.vwap?'↑':'↓'}`,          ok: isLong ? r.ltp>r.vwap : r.ltp<r.vwap },
        { label: `ADX ${r.adx?.toFixed(0)}`,         ok: r.adx >= 25 },
        { label: `Vol ${r.volume_ratio?.toFixed(1)}x`, ok: r.volume_ratio >= 1.3 },
        { label: `EMA ${r.ema_fast>r.ema_slow?'↑':'↓'}`,  ok: isLong ? r.ema_fast>r.ema_slow : r.ema_fast<r.ema_slow },
    ].map(p =>
        `<span class="sc-pill ${p.ok ? 'green' : 'red'}">${p.label}</span>`
    ).join('');
}

// ─── QUICK ANALYSE ───────────────────────────────────────────
async function quickAnalyse() {
    const sym = (document.getElementById('sc-quick-sym')?.value || '').trim().toUpperCase();
    if (!sym) { showToast('Symbol daalo!', 'toast-error'); return; }
    const tf = document.getElementById('sc-timeframe')?.value || 'day';

    showModal(sym, `<div class="sc-modal-loading">⏳ ${sym} ka analysis ho raha hai...</div>`);

    const res = await api('/api/scanner/analyse', 'POST', { symbol: sym, timeframe: tf });

    if (!res) {
        setHTML('sc-modal-body', '<div class="sc-modal-error">❌ Server error</div>'); return;
    }
    if (!res.success) {
        setHTML('sc-modal-body',
            res.no_signal
                ? `<div class="sc-modal-nosig">
                        <div style="font-size:36px;margin-bottom:10px">😐</div>
                        <b style="color:var(--yellow)">${sym} - No Strong Signal</b>
                        <p style="color:var(--text2);margin-top:8px;font-size:13px">
                            ${res.error || 'Score threshold meet nahi hua.'}<br>
                            Alag timeframe try karo ya thoda wait karo setup ke liye.
                        </p>
                   </div>`
                : `<div class="sc-modal-error">❌ ${res.error}</div>`);
        return;
    }
    setText('sc-modal-title', `${res.signal.symbol} — ${res.signal.signal_type}`);
    setHTML('sc-modal-body', signalCard(res.signal));
}

function showModal(title, body) {
    setText('sc-modal-title', title);
    setHTML('sc-modal-body', body);
    _setDisplay('sc-modal', 'flex');
}

function closeModal() { _setDisplay('sc-modal', 'none'); }

document.addEventListener('click', e => {
    const m = document.getElementById('sc-modal');
    if (m && e.target === m) closeModal();
});

// ─── UTIL ────────────────────────────────────────────────────
function _setDisplay(id, val) {
    const el = document.getElementById(id);
    if (el) el.style.display = val;
}

// ─────────────────────────────────────────────────────────────
// QUICK ORDER - Scanner card mein inline BUY/SELL
// ─────────────────────────────────────────────────────────────
let _qoData = {};

function quickOrder(symbol, direction, entry, sl, t1, t2, t3, tag) {
    const isLong   = direction === 'BUY';
    const dirCls   = isLong ? 'long' : 'short';
    const dirIcon  = isLong ? '📈' : '📉';
    const dirLabel = isLong ? 'BUY' : 'SELL';

    // Safe toFixed - handle undefined/null
    const fmt    = (v) => (v && !isNaN(v)) ? parseFloat(v).toFixed(2) : '0.00';
    const fmtPct = (a, b) => (a && b && b > 0) ? ((Math.abs(a - b) / b) * 100).toFixed(1) : '0.0';

    const numEntry = parseFloat(entry) || 0;
    const numSl    = parseFloat(sl) || 0;
    const numT1    = parseFloat(t1) || 0;
    const numT2    = parseFloat(t2) || 0;
    const numT3    = parseFloat(t3) || 0;

    const slDiff  = fmtPct(numSl, numEntry);
    const t1Diff  = fmtPct(numT1, numEntry);
    const t2Diff  = fmtPct(numT2, numEntry);
    const riskAmt = (numEntry && numSl) ? Math.abs(numEntry - numSl).toFixed(2) : '0.00';
    const initMargin = (numEntry / 5.0).toFixed(0);

    // Store for confirm step
    _qoData = {
        symbol,
        direction,
        entry: numEntry,
        sl: numSl,
        t1: numT1,
        t2: numT2,
        t3: numT3,
        tag: tag || 'QUICK_ORDER'
    };

    const modalHTML = `
<div class="qo-form">
    <div class="qo-header ${dirCls}">
        <span class="qo-symbol">${symbol}</span>
        <span class="qo-dir-tag ${dirCls}">${dirIcon} ${dirLabel}</span>
    </div>

    <div class="qo-levels">
        <div class="qo-level-item">
            <div class="qo-level-lbl">⚡ Entry</div>
            <div class="qo-level-val green">₹${fmt(numEntry)}</div>
        </div>
        <div class="qo-level-item">
            <div class="qo-level-lbl">🛑 Stop Loss</div>
            <div class="qo-level-val red">₹${fmt(numSl)}</div>
            <div class="qo-level-sub red">-${slDiff}%</div>
        </div>
        <div class="qo-level-item">
            <div class="qo-level-lbl">🎯 Target 1</div>
            <div class="qo-level-val" style="color:#fbbf24">₹${fmt(numT1)}</div>
            <div class="qo-level-sub dim">+${t1Diff}%</div>
        </div>
        <div class="qo-level-item">
            <div class="qo-level-lbl">🎯 Target 2</div>
            <div class="qo-level-val" style="color:#34d399">₹${fmt(numT2)}</div>
            <div class="qo-level-sub dim">+${t2Diff}%</div>
        </div>
    </div>

    <div class="qo-qty-section">
        <label class="qo-label">Quantity (Shares)</label>
        <div class="qo-qty-wrap">
            <button class="qo-qty-btn" type="button" onclick="adjustQty(-1)">−</button>
            <input type="number" id="qo-qty" value="1" min="1"
                   oninput="calcQoValue()">
            <button class="qo-qty-btn" type="button" onclick="adjustQty(1)">+</button>
        </div>
    </div>

    <div class="qo-prod-section">
        <label class="qo-label">Product Type</label>
        <select id="qo-product" class="qo-select" onchange="calcQoValue()">
            <option value="MIS" selected>MIS — Intraday (5X Margin)</option>
            <option value="CNC">CNC — Delivery (1X Cash)</option>
        </select>
    </div>

    <div class="qo-calc-bar">
        <div class="qo-calc-item">
            <span class="dim">Est. Value</span>
            <b id="qo-est-val">₹${fmt(numEntry)}</b>
        </div>
        <div class="qo-calc-item">
            <span class="dim">Margin Req.</span>
            <b id="qo-margin-val" style="color:var(--accent)">₹${initMargin} (5X)</b>
        </div>
        <div class="qo-calc-item">
            <span class="dim">Max Risk</span>
            <b id="qo-max-risk" class="red">₹${riskAmt}</b>
        </div>
        <div class="qo-calc-item">
            <span class="dim">Risk/Share</span>
            <b class="dim">₹${riskAmt}</b>
        </div>
    </div>

    <button class="qo-submit ${dirCls}" id="qo-submit-btn"
            type="button" onclick="confirmQuickOrder()">
        ${dirIcon} Place ${dirLabel} Order — ${symbol}
    </button>

    <p id="qo-paper-note" class="qo-paper-note"></p>
</div>`;

    setText('sc-qo-title', `${dirIcon} Quick ${dirLabel} — ${symbol}`);
    setHTML('sc-qo-body',  modalHTML);

    // Paper mode check
    fetch('/api/status')
        .then(r => r.json())
        .then(st => {
            const noteEl = document.getElementById('qo-paper-note');
            if (noteEl && st.is_paper) {
                noteEl.textContent = '📄 PAPER MODE — 5X Margin Enabled for Intraday (MIS)';
            }
        })
        .catch(() => {});

    // Show modal
    const modal = document.getElementById('sc-qo-modal');
    if (modal) modal.style.display = 'flex';
}

function adjustQty(delta) {
    const input = document.getElementById('qo-qty');
    if (!input) return;
    const newVal = Math.max(1, (parseInt(input.value) || 1) + delta);
    input.value  = newVal;
    calcQoValue();
}

function calcQoValue() {
    const qtyInput = document.getElementById('qo-qty');
    const qty      = Math.max(1, parseInt(qtyInput?.value || 1));
    const entry    = _qoData.entry || 0;
    const product  = document.getElementById('qo-product')?.value || 'MIS';
    const riskPerShare = Math.abs((_qoData.entry || 0) - (_qoData.sl || 0));

    const estEl    = document.getElementById('qo-est-val');
    const marginEl = document.getElementById('qo-margin-val');
    const riskEl   = document.getElementById('qo-max-risk');

    const totalVal  = qty * entry;
    const marginReq = (product === 'MIS') ? (totalVal / 5.0) : totalVal;

    if (estEl)    estEl.textContent  = '₹' + Math.round(totalVal).toLocaleString('en-IN');
    if (marginEl) marginEl.textContent = '₹' + Math.ceil(marginReq).toLocaleString('en-IN') + (product === 'MIS' ? ' (5X)' : ' (1X)');
    if (riskEl)   riskEl.textContent = '₹' + (qty * riskPerShare).toFixed(0);
}

async function confirmQuickOrder() {
    const qtyInput = document.getElementById('qo-qty');
    const qty      = parseInt(qtyInput?.value  || 0);
    const product  = document.getElementById('qo-product')?.value || 'MIS';
    const btn      = document.getElementById('qo-submit-btn');

    if (qty <= 0) {
        showToast('Quantity 1 ya zyada honi chahiye!', 'toast-error');
        return;
    }
    if (!_qoData.symbol) {
        showToast('Order data missing! Dobara try karo.', 'toast-error');
        return;
    }

    // Disable button
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Placing order...'; }

    try {
        const res  = await fetch('/api/trade/place', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol:      _qoData.symbol,
                exchange:    'NSE',
                transaction: _qoData.direction,
                quantity:    qty,
                order_type:  'MARKET',
                product:     product,
                price:       0,
                stop_loss:   _qoData.sl || 0,
                target:      _qoData.t1 || 0,
                tag:         _qoData.tag || 'QUICK_ORDER',
            }),
        });
        const data = await res.json();

        if (data.success) {
            showToast(
                data.paper_mode
                    ? `📄 PAPER: ${_qoData.direction} ${qty} ${_qoData.symbol} order placed (MIS 5X Margin)`
                    : `✅ ${_qoData.direction} ${qty} ${_qoData.symbol} order placed! ID: ${(data.order_id||'').substring(0,12)}`,
                'toast-success'
            );
            closeQuickOrder();
        } else {
            showToast(`❌ ${data.error || 'Order failed'}`, 'toast-error');
            if (btn) {
                btn.disabled    = false;
                btn.textContent = `${_qoData.direction === 'BUY' ? '📈' : '📉'} Place ${_qoData.direction} Order — ${_qoData.symbol}`;
            }
        }
    } catch (err) {
        showToast('❌ Network error: ' + err.message, 'toast-error');
        if (btn) {
            btn.disabled    = false;
            btn.textContent = `${_qoData.direction === 'BUY' ? '📈' : '📉'} Place ${_qoData.direction} Order — ${_qoData.symbol}`;
        }
    }
}

function closeQuickOrder() {
    const modal = document.getElementById('sc-qo-modal');
    if (modal) modal.style.display = 'none';
    _qoData = {};
}

// Backdrop click se band karo
document.addEventListener('click', e => {
    const m = document.getElementById('sc-qo-modal');
    if (m && e.target === m) closeQuickOrder();
});

// Escape key se band karo
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeQuickOrder();
        closeModal();
    }
});
