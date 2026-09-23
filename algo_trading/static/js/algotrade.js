/**
 * algotrade.js - Autonomous Algo Trade Page Controller
 * 100% Hands-Free Auto Buy / Auto Sell Engine
 *
 * Concepts Handled:
 * - Master Robot Controls (Start Auto-Pilot, Pause, Stop, Mode Switch, Kill Switch)
 * - Quantitative Strategy Toggles & Parameter Tuning
 * - Risk Management System (RMS) & Circuit Breakers
 * - Active Algo Positions Tracking with Dynamic Trailing Stop Loss
 * - Live Streaming Terminal Console (Scans, Signals, Auto Orders, Exits)
 * - Trade Analytics & Historical Execution Records
 */

let _algoPollInterval = null;
let _algoCurrentFilter = 'ALL';
let _algoStrategiesCache = {};
let _algoLastLogCount = 0;

// ─── INITIALIZATION ──────────────────────────────────────────
function initAlgoTradePage() {
    loadAlgoStatus();
    loadAlgoConfig();
    fetchAlgoPositions();
    fetchAlgoTrades();
    fetchAlgoLogs();
    loadAlgoEquityCurve();

    if (!_algoPollInterval) {
        _algoPollInterval = setInterval(() => {
            const page = document.getElementById('page-algotrade');
            if (page && page.classList.contains('active')) {
                loadAlgoStatus();
                fetchAlgoPositions();
                fetchAlgoLogs();
                loadAlgoEquityCurve();
            }
        }, 2000);
    }
}


// ─── 1. STATUS & KPI RENDERING ────────────────────────────────
async function loadAlgoStatus() {
    try {
        const res = await fetch('/api/algo/status');
        const data = await res.json();
        renderAlgoStatus(data);
    } catch (e) {
        console.error('Failed to load algo status:', e);
    }
}

function renderAlgoStatus(data) {
    if (!data) return;

    // Status Badge
    const statusBadge = document.getElementById('algo-status-badge');
    const startBtn = document.getElementById('algo-start-btn');
    const pauseBtn = document.getElementById('algo-pause-btn');
    const stopBtn = document.getElementById('algo-stop-btn');

    const status = data.status || 'STOPPED';

    if (status === 'RUNNING') {
        statusBadge.className = 'badge-pill green pulse-green';
        statusBadge.innerHTML = '● RUNNING (AUTO-PILOT)';
        if (startBtn) startBtn.style.display = 'none';
        if (pauseBtn) pauseBtn.style.display = 'inline-flex';
        if (stopBtn) stopBtn.style.display = 'inline-flex';
    } else if (status === 'PAUSED') {
        statusBadge.className = 'badge-pill yellow';
        statusBadge.innerHTML = '⏸ PAUSED (MONITORING)';
        if (startBtn) {
            startBtn.style.display = 'inline-flex';
            startBtn.innerText = '▶ Resume Auto-Pilot';
        }
        if (pauseBtn) pauseBtn.style.display = 'none';
        if (stopBtn) stopBtn.style.display = 'inline-flex';
    } else {
        statusBadge.className = 'badge-pill grey';
        statusBadge.innerHTML = '● STOPPED';
        if (startBtn) {
            startBtn.style.display = 'inline-flex';
            startBtn.innerText = '▶ Start Auto-Pilot';
        }
        if (pauseBtn) pauseBtn.style.display = 'none';
        if (stopBtn) stopBtn.style.display = 'none';
    }

    // Mode Badge & Toggle Buttons
    const mode = data.mode || 'PAPER';
    const modeBadge = document.getElementById('algo-mode-badge');
    const paperBtn = document.getElementById('algo-mode-paper-btn');
    const liveBtn = document.getElementById('algo-mode-live-btn');

    if (mode === 'PAPER') {
        modeBadge.className = 'badge-pill purple';
        modeBadge.innerHTML = '📄 PAPER (5X MARGIN)';
        if (paperBtn) paperBtn.classList.add('active');
        if (liveBtn) liveBtn.classList.remove('active');
    } else {
        modeBadge.className = 'badge-pill red pulse-red';
        modeBadge.innerHTML = '🔴 LIVE (ZERODHA)';
        if (paperBtn) paperBtn.classList.remove('active');
        if (liveBtn) liveBtn.classList.add('active');
    }

    // WebSocket Indicator & Scan Countdown
    const wsBadge = document.getElementById('algo-ws-badge');
    if (wsBadge) {
        if (data.websocket_connected) {
            const ticksCount = data.websocket_ticks_count || 0;
            wsBadge.className = 'badge-pill cyan';
            wsBadge.innerHTML = `📡 WS: REAL-TIME (<5ms) • ${ticksCount} Ticks`;
            wsBadge.title = 'KiteTicker WebSocket live streaming in memory (Sub-millisecond execution)';
        } else {
            wsBadge.className = 'badge-pill grey';
            wsBadge.innerHTML = '🌐 REST BATCH POLLING';
            wsBadge.title = 'Kite REST batch polling mode';
        }
    }

    const cdElem = document.getElementById('algo-scan-countdown');
    if (cdElem) {
        if (data.websocket_connected) {
            const ms = data.last_scan_duration_ms ? `${data.last_scan_duration_ms}ms` : '<5ms WS';
            cdElem.innerText = `⚡ ${ms}`;
        } else {
            const countdown = data.next_scan_countdown || 0;
            cdElem.innerText = `${countdown}s`;
        }
    }

    // KPIs
    const stats = data.stats || {};
    renderPnlElem('algo-kpi-net-pnl', stats.today_pnl || 0);
    renderPnlElem('algo-kpi-realized-pnl', stats.realized_pnl || 0);
    renderPnlElem('algo-kpi-unrealized-pnl', stats.unrealized_pnl || 0);

    const chargesVal = parseFloat(stats.today_charges !== undefined ? stats.today_charges : (stats.total_charges || 0)) || 0;
    const chargesElem = document.getElementById('algo-kpi-charges');
    if (chargesElem) {
        chargesElem.innerText = (chargesVal > 0 ? '-₹' : '₹') + Math.abs(chargesVal).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        chargesElem.className = 'algo-kpi-val ' + (chargesVal > 0 ? 'red' : '');
    }

    const activeCount = data.open_positions_count || 0;
    const maxPos = (data.risk_config && data.risk_config.max_open_positions) || 4;
    setText('algo-kpi-active-pos', `${activeCount} / ${maxPos}`);
    setText('algo-kpi-win-rate', `${stats.win_rate || 0}%`);
    setText('algo-kpi-total-trades', `${stats.total_trades || 0}`);
    setText('algo-kpi-signals-count', `${stats.signals_today || 0}`);

    // Circuit Breaker Alert
    const cbAlert = document.getElementById('algo-circuit-breaker-alert');
    if (data.circuit_breaker_hit) {
        if (cbAlert) {
            cbAlert.style.display = 'flex';
            setText('algo-cb-reason', data.circuit_breaker_reason || 'Daily Loss Limit Breached');
        }
    } else {
        if (cbAlert) cbAlert.style.display = 'none';
    }
}

function renderPnlElem(elemId, val) {
    const el = document.getElementById(elemId);
    if (!el) return;
    const v = parseFloat(val) || 0;
    el.innerText = (v >= 0 ? '+₹' : '-₹') + Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    el.className = 'algo-kpi-val ' + (v > 0 ? 'green' : v < 0 ? 'red' : '');
}

// ─── 2. MASTER CONTROLS & MODE TOGGLE ─────────────────────────
async function toggleAlgoBot(action) {
    try {
        const res = await fetch('/api/algo/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action })
        });
        const data = await res.json();
        if (data.success) {
            const labels = { start: 'Auto-Pilot Started! 🚀', pause: 'Auto-Pilot Paused ⏸️', stop: 'Auto-Pilot Stopped 🛑' };
            showToast(labels[action] || 'Bot updated', 'success');
            loadAlgoStatus();
        } else {
            showToast(data.error || 'Failed to update bot', 'error');
        }
    } catch (e) {
        showToast('Server communication error', 'error');
    }
}

async function setAlgoMode(mode) {
    if (mode === 'LIVE') {
        if (!confirm('⚠️ WARNING: Switching to LIVE TRADING mode will place REAL ORDERS on your Zerodha account using real money.\n\nAre you sure you want to proceed?')) {
            return;
        }
    }

    try {
        const res = await fetch('/api/algo/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: mode })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Mode switched to ${mode} TRADING`, 'success');
            loadAlgoStatus();
        } else {
            showToast(data.error || 'Failed to switch mode', 'error');
        }
    } catch (e) {
        showToast('Error switching mode', 'error');
    }
}

async function triggerAlgoScanNow() {
    const t0 = performance.now();
    const btn = document.getElementById('algo-scan-btn');
    if (btn) btn.disabled = true;

    try {
        const res = await fetch('/api/algo/scan_now', { method: 'POST' });
        const data = await res.json();
        const clientMs = Math.round(performance.now() - t0);

        if (data.success) {
            const ms = data.duration_ms !== undefined ? data.duration_ms : clientMs;
            const modeTxt = data.mode === 'WEBSOCKET' ? '📡 WebSocket Live Feed' : '🌐 REST Batch';
            const count = data.scanned_count || 0;
            showToast(`⚡ Millisecond Scan Executed in ${ms}ms (${modeTxt}) | ${count} stocks checked!`, 'success');
            loadAlgoStatus();
            fetchAlgoPositions();
            fetchAlgoLogs();
        } else {
            showToast(data.error || 'Failed to trigger scan', 'error');
        }
    } catch (e) {
        showToast('Failed to trigger scan: ' + e, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}


// ─── 3. EMERGENCY KILL SWITCH ─────────────────────────────────
function confirmKillSwitch() {
    const modal = document.getElementById('algo-kill-modal');
    if (modal) modal.style.display = 'flex';
}

function closeKillModal() {
    const modal = document.getElementById('algo-kill-modal');
    if (modal) modal.style.display = 'none';
}

async function executeKillSwitch() {
    closeKillModal();
    try {
        const res = await fetch('/api/algo/kill_switch', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || '🚨 Emergency Kill Switch Executed!', 'error');
            loadAlgoStatus();
            fetchAlgoPositions();
            fetchAlgoTrades();
            fetchAlgoLogs();
        } else {
            showToast(data.error || 'Kill switch error', 'error');
        }
    } catch (e) {
        showToast('Emergency trigger error', 'error');
    }
}

async function resetCircuitBreaker() {
    try {
        const res = await fetch('/api/algo/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ risk_config: { circuit_breaker_hit: false, circuit_breaker_reason: '' } })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Circuit breaker reset. Bot can now be started.', 'success');
            loadAlgoStatus();
        }
    } catch (e) {
        showToast('Failed to reset circuit breaker', 'error');
    }
}

// ─── 4. QUANTITATIVE STRATEGIES GRID ──────────────────────────
async function loadAlgoConfig() {
    try {
        const res = await fetch('/api/algo/config');
        const data = await res.json();
        if (data) {
            // Universe
            if (data.universe) {
                const uSel = document.getElementById('algo-universe-select');
                if (uSel) uSel.value = data.universe;
            }

            // RMS Fields
            if (data.risk_config) {
                const rc = data.risk_config;
                setVal('algo-rms-max-loss', rc.max_daily_loss || 5000);
                setVal('algo-rms-max-profit', rc.max_daily_profit || 15000);
                setVal('algo-rms-max-positions', rc.max_open_positions || 4);
                setVal('algo-rms-min-winrate', rc.min_win_rate_pct || 60);
            }

            // Strategies Grid
            if (data.strategies) {
                _algoStrategiesCache = {};
                data.strategies.forEach(s => _algoStrategiesCache[s.id] = s);
                renderStrategiesGrid(data.strategies);
            }
        }
    } catch (e) {
        console.error('Failed to load algo config:', e);
    }
}

function renderStrategiesGrid(strategies) {
    const grid = document.getElementById('algo-strategies-grid');
    if (!grid) return;

    if (!strategies || strategies.length === 0) {
        grid.innerHTML = '<div class="empty">No strategies configured</div>';
        return;
    }

    grid.innerHTML = strategies.map(s => {
        const enabled = s.enabled !== false;
        const icon = s.icon || '📈';
        const badge = s.badge || s.timeframe || 'Intraday';
        const target1Pct = s.target_1_pct != null ? s.target_1_pct : 1.0;
        const target2Pct = s.target_2_pct != null ? s.target_2_pct : (s.target_pct || 2.0);
        const slPct = s.sl_pct || 0.8;
        const trailPct = s.trailing_sl_pct || 0.3;
        const cap = (s.capital_per_trade || 20000).toLocaleString('en-IN');
        const prod = s.product || 'MIS';
        const isMis = (prod === 'MIS');
        const signalsCount = s.signals_count || 0;

        return `
            <div class="algo-strat-card ${enabled ? 'active-strat' : 'disabled-strat'}" id="strat-card-${s.id}">
                <div class="strat-card-header">
                    <div class="strat-title-group">
                        <span class="strat-icon">${icon}</span>
                        <div>
                            <div class="strat-name">${s.name}</div>
                            <span class="badge-mini purple">${badge}</span>
                        </div>
                    </div>
                    <label class="algo-switch" title="Toggle Strategy Auto-Trading">
                        <input type="checkbox" id="chk-strat-${s.id}" ${enabled ? 'checked' : ''} onchange="toggleStrategyState('${s.id}', this.checked)">
                        <span class="algo-slider"></span>
                    </label>
                </div>

                <div class="strat-card-desc">${s.desc || ''}</div>

                <div class="strat-params-grid">
                    <div class="strat-param">
                        <span class="param-lbl">Target 1 (50%)</span>
                        <span class="param-val green">+${target1Pct}%</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">Target 2 (Runner)</span>
                        <span class="param-val green">+${target2Pct}%</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">Stop Loss</span>
                        <span class="param-val red">-${slPct}%</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">Trailing SL</span>
                        <span class="param-val yellow">${trailPct}% step</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">Timeframe</span>
                        <span class="param-val cyan">${s.timeframe || '5m'}</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">Capital / Trade</span>
                        <span class="param-val">₹${cap}</span>
                    </div>
                </div>

                <div class="strat-card-footer">
                    <div class="strat-signals-badge">
                        <span>🎯 Signals:</span> <strong>${signalsCount}</strong>
                    </div>
                    <button class="btn btn-sm btn-grey" onclick="openAlgoStratModal('${s.id}')">
                        ⚙️ Configure
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

async function toggleStrategyState(stratId, isEnabled) {
    if (_algoStrategiesCache[stratId]) {
        _algoStrategiesCache[stratId].enabled = isEnabled;
    }

    const card = document.getElementById(`strat-card-${stratId}`);
    if (card) {
        if (isEnabled) {
            card.classList.add('active-strat');
            card.classList.remove('disabled-strat');
        } else {
            card.classList.remove('active-strat');
            card.classList.add('disabled-strat');
        }
    }

    try {
        const res = await fetch('/api/algo/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                strategies: [{ id: stratId, enabled: isEnabled }]
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`${_algoStrategiesCache[stratId]?.name || 'Strategy'} ${isEnabled ? 'ENABLED' : 'DISABLED'} for Auto Trading`, 'info');
        }
    } catch (e) {
        showToast('Failed to toggle strategy', 'error');
    }
}

// ─── 5. STRATEGY MODAL CONFIGURATION ──────────────────────────
function openAlgoStratModal(stratId) {
    const s = _algoStrategiesCache[stratId];
    if (!s) return;

    setVal('algo-modal-strat-id', s.id);
    setText('algo-modal-strat-title', `${s.name} Configuration`);
    setText('algo-modal-strat-icon', s.icon || '⚙️');
    setText('algo-modal-strat-sub', `Configure execution rules for ${s.name}`);

    setVal('algo-modal-enabled', (s.enabled !== false).toString());
    setVal('algo-modal-timeframe', s.timeframe || '5m');
    setVal('algo-modal-target1-pct', s.target_1_pct != null ? s.target_1_pct : 1.0);
    setVal('algo-modal-target2-pct', s.target_2_pct != null ? s.target_2_pct : 2.0);
    setVal('algo-modal-sl-pct', s.sl_pct || 0.8);
    setVal('algo-modal-trail-pct', s.trailing_sl_pct || 0.3);
    setVal('algo-modal-capital', s.capital_per_trade || 20000);
    setVal('algo-modal-product', s.product || 'MIS');
    setVal('algo-modal-side', s.side || 'BOTH');

    const modal = document.getElementById('algo-strat-modal');
    if (modal) modal.style.display = 'flex';
}

function closeAlgoStratModal() {
    const modal = document.getElementById('algo-strat-modal');
    if (modal) modal.style.display = 'none';
}

async function saveAlgoStratModal() {
    const stratId = document.getElementById('algo-modal-strat-id').value;
    if (!stratId) return;

    const t1Pct = parseFloat(document.getElementById('algo-modal-target1-pct').value) || 1.0;
    const t2Pct = parseFloat(document.getElementById('algo-modal-target2-pct').value) || 2.0;

    const payload = {
        id: stratId,
        enabled: document.getElementById('algo-modal-enabled').value === 'true',
        timeframe: document.getElementById('algo-modal-timeframe').value,
        target_1_pct: t1Pct,
        target_2_pct: t2Pct,
        target_pct: t2Pct,
        sl_pct: parseFloat(document.getElementById('algo-modal-sl-pct').value) || 0.8,
        trailing_sl_pct: parseFloat(document.getElementById('algo-modal-trail-pct').value) || 0.3,
        capital_per_trade: parseFloat(document.getElementById('algo-modal-capital').value) || 20000,
        product: document.getElementById('algo-modal-product').value,
        side: document.getElementById('algo-modal-side').value,
    };


    try {
        const res = await fetch('/api/algo/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategies: [payload] })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Strategy configuration saved!', 'success');
            closeAlgoStratModal();
            loadAlgoConfig();
        } else {
            showToast(data.error || 'Failed to save config', 'error');
        }
    } catch (e) {
        showToast('Error saving strategy settings', 'error');
    }
}

// ─── 6. RMS RISK CONTROLS SAVING ──────────────────────────────
async function saveAlgoRMS() {
    const universe = document.getElementById('algo-universe-select').value;
    const maxLoss = parseFloat(document.getElementById('algo-rms-max-loss').value) || 5000;
    const maxProfit = parseFloat(document.getElementById('algo-rms-max-profit').value) || 15000;
    const maxPos = parseInt(document.getElementById('algo-rms-max-positions').value) || 4;
    const minWinRate = parseFloat(document.getElementById('algo-rms-min-winrate').value) || 60;

    try {
        const res = await fetch('/api/algo/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                universe: universe,
                risk_config: {
                    max_daily_loss: maxLoss,
                    max_daily_profit: maxProfit,
                    max_open_positions: maxPos,
                    min_win_rate_pct: minWinRate,
                }
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast('🛡️ Risk Management Rules Saved!', 'success');
            loadAlgoStatus();
        } else {
            showToast(data.error || 'Failed to save RMS', 'error');
        }
    } catch (e) {
        showToast('Error saving RMS rules', 'error');
    }
}

function updateAlgoRMS() {
    saveAlgoRMS();
}

// ─── 7. ACTIVE ALGO POSITIONS TABLE ───────────────────────────
async function fetchAlgoPositions() {
    try {
        const res = await fetch('/api/algo/positions');
        const positions = await res.json();
        renderAlgoPositionsTable(positions);
    } catch (e) {
        console.error('Error fetching algo positions:', e);
    }
}

function renderAlgoPositionsTable(positions) {
    const tbody = document.getElementById('algo-positions-tbody');
    const badge = document.getElementById('algo-active-pos-count');
    if (!tbody) return;

    if (!positions || positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="14" class="empty">No active positions open. Start bot to scan for auto entries.</td></tr>';
        if (badge) badge.innerText = '0 Open';
        return;
    }

    if (badge) badge.innerText = `${positions.length} Open`;

    tbody.innerHTML = positions.map(p => {
        const sideClass = (p.side === 'BUY') ? 'badge-mini green' : 'badge-mini red';
        const pnl = p.pnl || 0;
        const pnlPct = p.pnl_pct || 0;
        const pnlColor = pnl >= 0 ? 'green' : 'red';
        const pnlSign = pnl >= 0 ? '+' : '';
        const tvUrl = `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(p.symbol)}`;

        const t1 = p.target_1 || p.target || 0;
        const t2 = p.target_2 || (p.entry_price ? (p.side === 'BUY' ? p.entry_price * 1.02 : p.entry_price * 0.98) : 0);

        const isRiskFree = !!p.target_1_hit;
        const statusBadge = isRiskFree
            ? `<span class="badge-mini risk-free" title="Target 1 hit! 50% profit booked &amp; SL moved to Cost (Risk-Free)">🛡️ RISK-FREE (T1 HIT)</span>`
            : `<span class="badge-mini blue">MONITORING</span>`;

        const grossPnl = p.gross_pnl !== undefined ? p.gross_pnl : pnl;
        const grossColor = grossPnl >= 0 ? 'green' : 'red';
        const grossSign = grossPnl >= 0 ? '+' : '';
        const charges = p.charges || 0;

        let chargesTip = `Est. Round-Trip Charges: ₹${charges.toFixed(2)}`;
        if (p.charges_breakdown && typeof p.charges_breakdown === 'object') {
            const parts = Object.entries(p.charges_breakdown).map(([k, v]) => `${k}: ${v}`);
            chargesTip = `Est. Round-Trip Charges: ₹${charges.toFixed(2)} (${parts.join(' | ')})`;
        }

        return `
            <tr>
                <td>
                    <a href="${tvUrl}" target="_blank" rel="noopener noreferrer" class="stock-chart-link" title="Open ${p.symbol} Chart on TradingView">
                        <span class="stock-sym-text">${p.symbol}</span>
                        <span class="stock-chart-arrow">↗</span>
                    </a>
                </td>
                <td>
                    <span class="badge-mini purple">${p.strategy_name || 'Algo'}</span>
                    <span class="badge-mini cyan" title="Setup Win Rate Probability">🔥 ${p.win_rate || 60}% WR</span>
                </td>
                <td><span class="${sideClass}">${p.side}</span></td>
                <td><span class="badge-mini blue">${p.product} (5X)</span></td>
                <td>${p.quantity}</td>
                <td>₹${(p.entry_price || 0).toFixed(2)}</td>
                <td><strong>₹${(p.current_price || p.entry_price || 0).toFixed(2)}</strong></td>
                <td class="red">₹${(p.stop_loss || 0).toFixed(2)}</td>
                <td class="yellow"><strong>₹${(p.trailing_sl || p.stop_loss || 0).toFixed(2)}</strong></td>
                <td class="green">₹${t1.toFixed(2)}</td>
                <td class="green">₹${t2.toFixed(2)}</td>
                <td class="${pnlColor}">
                    <div><strong>${pnlSign}₹${Math.abs(pnl).toFixed(2)}</strong> <small>(${pnlSign}${pnlPct.toFixed(2)}%)</small></div>
                    <div style="font-size:10px;opacity:0.85;margin-top:2px;white-space:nowrap;" title="${escapeHtml(chargesTip)}">
                        Gross: <span class="${grossColor}">${grossSign}₹${Math.abs(grossPnl).toFixed(2)}</span>
                        <span style="color:var(--text3)"> | </span>
                        Chg: <span class="red" style="text-decoration:underline dotted;cursor:help;">-₹${charges.toFixed(2)}</span>
                    </div>
                </td>
                <td>${statusBadge}</td>
                <td>
                    <button class="btn btn-sm btn-red" onclick="exitAlgoPosition('${p.pos_id}')" title="Manual Square Off">
                        Square Off
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}


async function exitAlgoPosition(posId) {
    if (!confirm('Are you sure you want to manually square off this position?')) return;

    try {
        const res = await fetch('/api/algo/position/exit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pos_id: posId })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || 'Position squared off', 'success');
            fetchAlgoPositions();
            fetchAlgoTrades();
            fetchAlgoLogs();
        } else {
            showToast(data.error || 'Failed to exit position', 'error');
        }
    } catch (e) {
        showToast('Error exiting position', 'error');
    }
}

// ─── 8. LIVE TERMINAL LOGS CONSOLE ────────────────────────────
async function fetchAlgoLogs() {
    try {
        const res = await fetch('/api/algo/logs?limit=200');
        const logs = await res.json();
        renderAlgoLogs(logs);
    } catch (e) {
        console.error('Error fetching algo logs:', e);
    }
}

function renderAlgoLogs(logs) {
    const termBody = document.getElementById('algo-terminal-body');
    if (!termBody || !logs) return;

    // Filter logs
    const filtered = (_algoCurrentFilter === 'ALL')
        ? logs
        : logs.filter(l => (l.level || '').toUpperCase() === _algoCurrentFilter);

    if (filtered.length === 0) {
        termBody.innerHTML = '<div class="term-line muted"><span class="term-time">[--:--:--]</span> No activity logs matching selected filter.</div>';
        return;
    }

    termBody.innerHTML = filtered.map(l => {
        const lvl = (l.level || 'INFO').toUpperCase();
        let cssClass = 'info';
        if (lvl === 'SIGNAL') cssClass = 'signal';
        else if (lvl === 'ORDER') cssClass = 'order';
        else if (lvl === 'TRAIL') cssClass = 'trail';
        else if (lvl === 'EXIT') cssClass = 'exit';
        else if (lvl === 'ALERT' || lvl === 'ERROR') cssClass = 'alert';
        else if (lvl === 'SCAN') cssClass = 'scan';

        const detailSpan = l.details ? `<span class="term-details"> | ${escapeHtml(l.details)}</span>` : '';

        return `
            <div class="term-line ${cssClass}">
                <span class="term-time">[${l.time}]</span>
                <span class="term-tag ${cssClass}">[${lvl}]</span>
                <span class="term-msg">${escapeHtml(l.message)}</span>
                ${detailSpan}
            </div>
        `;
    }).join('');

    // Auto scroll if enabled
    const autoScroll = document.getElementById('algo-autoscroll-chk');
    if (autoScroll && autoScroll.checked) {
        termBody.scrollTop = termBody.scrollHeight;
    }
}

function filterAlgoLogs(filterName) {
    _algoCurrentFilter = filterName;
    document.querySelectorAll('.algo-term-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filterName);
    });
    fetchAlgoLogs();
}

function clearAlgoLogs() {
    const termBody = document.getElementById('algo-terminal-body');
    if (termBody) {
        termBody.innerHTML = '<div class="term-line muted"><span class="term-time">[00:00:00]</span> Console cleared by user.</div>';
    }
}

// ─── 9. COMPLETED TRADES HISTORY ──────────────────────────────
async function fetchAlgoTrades() {
    try {
        const res = await fetch('/api/algo/trades?limit=50');
        const trades = await res.json();
        renderAlgoTradesTable(trades);
    } catch (e) {
        console.error('Error fetching algo trades:', e);
    }
}

async function clearAlgoTrades() {
    if (!confirm('Are you sure you want to clear the completed trades history?')) return;
    try {
        const res = await fetch('/api/algo/trades/clear', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast('Trades history cleared!', 'info');
            fetchAlgoTrades();
        } else {
            showToast(data.error || 'Failed to clear trades', 'error');
        }
    } catch (e) {
        showToast('Error clearing trades', 'error');
    }
}


function renderAlgoTradesTable(trades) {
    const tbody = document.getElementById('algo-trades-tbody');
    const badge = document.getElementById('algo-closed-trades-count');
    if (!tbody) return;

    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="14" class="empty">No completed trades yet today.</td></tr>';
        if (badge) badge.innerText = '0 Closed';
        return;
    }

    if (badge) badge.innerText = `${trades.length} Closed`;

    tbody.innerHTML = trades.map(t => {
        const pnl = t.pnl || 0;
        const pnlPct = t.pnl_pct || 0;
        const pnlColor = pnl >= 0 ? 'green' : 'red';
        const pnlSign = pnl >= 0 ? '+' : '';

        const grossPnl = t.gross_pnl !== undefined ? t.gross_pnl : pnl;
        const grossColor = grossPnl >= 0 ? 'green' : 'red';
        const grossSign = grossPnl >= 0 ? '+' : '';

        const charges = t.charges || 0;
        let chargesTip = `Total Charges: ₹${charges.toFixed(2)}`;
        if (t.charges_breakdown && typeof t.charges_breakdown === 'object') {
            const parts = Object.entries(t.charges_breakdown).map(([k, v]) => `${k}: ${v}`);
            chargesTip = parts.join(' | ');
        }

        const tvUrl = `https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(t.symbol)}`;

        let reasonBadge = 'badge-mini grey';
        const r = t.exit_reason || '';
        if (r === 'TARGET_2_HIT' || r === 'TARGET_HIT') reasonBadge = 'badge-mini green glow';
        else if (r === 'TARGET_1_HIT') reasonBadge = 'badge-mini green';
        else if (r === 'COST_SL_HIT') reasonBadge = 'badge-mini purple';
        else if (r === 'STOP_LOSS_HIT') reasonBadge = 'badge-mini red';
        else if (r === 'TIME_CUTOFF') reasonBadge = 'badge-mini yellow';
        else if (r === 'KILL_SWITCH') reasonBadge = 'badge-mini red';

        return `
            <tr>
                <td>
                    <a href="${tvUrl}" target="_blank" rel="noopener noreferrer" class="stock-chart-link" title="Open ${t.symbol} Chart on TradingView">
                        <span class="stock-sym-text">${t.symbol}</span>
                        <span class="stock-chart-arrow">↗</span>
                    </a>
                </td>
                <td>
                    <span class="badge-mini purple">${t.strategy || 'Algo'}</span>
                    <span class="badge-mini cyan" title="Setup Win Rate Probability">🔥 ${t.win_rate || 60}% WR</span>
                </td>
                <td><span class="badge-mini ${t.side === 'BUY' ? 'green' : 'red'}">${t.side}</span></td>
                <td><span class="badge-mini blue">${t.product || 'MIS'}</span></td>
                <td>${t.quantity}</td>
                <td>₹${(t.entry_price || 0).toFixed(2)}</td>
                <td>₹${(t.exit_price || 0).toFixed(2)}</td>
                <td class="${grossColor}">${grossSign}₹${Math.abs(grossPnl).toFixed(2)}</td>
                <td>
                    <span class="badge-mini red" title="${escapeHtml(chargesTip)}" style="cursor:help;">-₹${charges.toFixed(2)}</span>
                </td>
                <td class="${pnlColor}"><strong>${pnlSign}₹${Math.abs(pnl).toFixed(2)}</strong></td>
                <td class="${pnlColor}">${pnlSign}${pnlPct.toFixed(2)}%</td>
                <td>${t.duration || '--'}</td>
                <td><span class="${reasonBadge}">${t.exit_reason || 'EXIT'}</span></td>
                <td>${t.exit_time || '--'}</td>
            </tr>
        `;
    }).join('');
}

// ─── 10. LIVE INTRADAY P&L EQUITY CURVE CHART ─────────────────
async function loadAlgoEquityCurve() {
    try {
        const res = await fetch('/api/algo/equity');
        const points = await res.json();
        renderEquityChart(points);
    } catch (e) {
        console.error('Failed to load algo equity curve:', e);
    }
}

function renderEquityChart(points) {
    const canvas = document.getElementById('algo-equity-canvas');
    if (!canvas) return;

    if (!Array.isArray(points) || points.length === 0) {
        points = [{ time: '09:15:00', pnl: 0, realized: 0, unrealized: 0 }];
    }

    // Latest P&L
    const latest = points[points.length - 1];
    const currPnl = (latest && latest.pnl != null) ? latest.pnl : 0;

    // Peak & Max Drawdown Calculation
    let peak = 0;
    let maxDd = 0;
    for (const pt of points) {
        const p = pt.pnl || 0;
        if (p > peak) peak = p;
        const dd = peak - p;
        if (dd > maxDd) maxDd = dd;
    }

    const currEl = document.getElementById('algo-eq-curr');
    const peakEl = document.getElementById('algo-eq-peak');
    const ddEl = document.getElementById('algo-eq-dd');

    if (currEl) {
        const sign = currPnl >= 0 ? '+' : '-';
        currEl.innerText = `${sign}₹${Math.abs(currPnl).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        currEl.className = currPnl >= 0 ? 'green' : 'red';
    }
    if (peakEl) {
        peakEl.innerText = `+₹${peak.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        peakEl.className = 'green';
    }
    if (ddEl) {
        ddEl.innerText = maxDd > 0 ? `-₹${maxDd.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '₹0.00';
        ddEl.className = maxDd > 0 ? 'red' : '';
    }

    // High-DPI canvas setup
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.clientWidth || 800;
    const height = 130;

    canvas.width = width * dpr;
    canvas.height = height * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const padLeft = 20;
    const padRight = 75;
    const padTop = 16;
    const padBottom = 24;
    const plotW = Math.max(10, width - padLeft - padRight);
    const plotH = Math.max(10, height - padTop - padBottom);

    ctx.clearRect(0, 0, width, height);

    // Min and Max Y
    let minY = Math.min(0, ...points.map(p => p.pnl || 0));
    let maxY = Math.max(0, ...points.map(p => p.pnl || 0));

    const range = Math.max(50, maxY - minY);
    minY -= range * 0.15;
    maxY += range * 0.15;
    const ySpan = maxY - minY || 1;

    const getX = (idx) => {
        if (points.length <= 1) return padLeft + plotW / 2;
        return padLeft + (idx / (points.length - 1)) * plotW;
    };
    const getY = (val) => {
        return padTop + plotH - ((val - minY) / ySpan) * plotH;
    };

    // Draw Dashed Baseline at Zero
    const zeroY = getY(0);
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.moveTo(padLeft, zeroY);
    ctx.lineTo(width - padRight, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Baseline label
    ctx.font = '10px Consolas, monospace';
    ctx.fillStyle = '#64748b';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('₹0.00', width - padRight + 8, zeroY);

    // Peak label on right
    if (maxY > 0) {
        ctx.fillStyle = '#10b981';
        ctx.fillText(`+₹${Math.round(maxY)}`, width - padRight + 8, padTop + 6);
    }
    // Min label on right
    if (minY < 0) {
        ctx.fillStyle = '#ef4444';
        ctx.fillText(`-₹${Math.round(Math.abs(minY))}`, width - padRight + 8, padTop + plotH - 2);
    }

    if (points.length === 1) {
        const x = getX(0);
        const y = getY(points[0].pnl || 0);
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, 2 * Math.PI);
        ctx.fillStyle = points[0].pnl >= 0 ? '#10b981' : '#ef4444';
        ctx.fill();
        return;
    }

    // Color gradient & stroke
    const isProfitable = currPnl >= 0;
    const strokeColor = isProfitable ? '#10b981' : '#ef4444';
    const fillTop = isProfitable ? 'rgba(16, 185, 129, 0.28)' : 'rgba(239, 68, 68, 0.28)';
    const fillBottom = 'rgba(0, 0, 0, 0.0)';

    // Gradient fill under curve
    const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, fillBottom);

    ctx.beginPath();
    ctx.moveTo(getX(0), getY(points[0].pnl || 0));

    for (let i = 0; i < points.length - 1; i++) {
        const x0 = getX(i);
        const y0 = getY(points[i].pnl || 0);
        const x1 = getX(i + 1);
        const y1 = getY(points[i + 1].pnl || 0);
        const xc = (x0 + x1) / 2;
        ctx.bezierCurveTo(xc, y0, xc, y1, x1, y1);
    }

    ctx.lineTo(getX(points.length - 1), padTop + plotH);
    ctx.lineTo(getX(0), padTop + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Line Stroke with Glow
    ctx.save();
    ctx.beginPath();
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 2.2;
    ctx.shadowColor = strokeColor;
    ctx.shadowBlur = 8;
    ctx.moveTo(getX(0), getY(points[0].pnl || 0));

    for (let i = 0; i < points.length - 1; i++) {
        const x0 = getX(i);
        const y0 = getY(points[i].pnl || 0);
        const x1 = getX(i + 1);
        const y1 = getY(points[i + 1].pnl || 0);
        const xc = (x0 + x1) / 2;
        ctx.bezierCurveTo(xc, y0, xc, y1, x1, y1);
    }
    ctx.stroke();
    ctx.restore();

    // Glowing Pulse Head at latest point
    const lastX = getX(points.length - 1);
    const lastY = getY(currPnl);

    ctx.beginPath();
    ctx.arc(lastX, lastY, 5, 0, 2 * Math.PI);
    ctx.fillStyle = strokeColor;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(lastX, lastY, 2, 0, 2 * Math.PI);
    ctx.fillStyle = '#ffffff';
    ctx.fill();

    // Time Axis labels
    ctx.font = '9.5px Consolas, monospace';
    ctx.fillStyle = '#64748b';
    ctx.textAlign = 'left';
    ctx.fillText(points[0].time || '', padLeft, height - 6);

    ctx.textAlign = 'right';
    ctx.fillText(points[points.length - 1].time || '', width - padRight, height - 6);
}

// Re-render chart on window resize
window.addEventListener('resize', () => {
    const page = document.getElementById('page-algotrade');
    if (page && page.classList.contains('active')) {
        loadAlgoEquityCurve();
    }
});


// ─── HELPERS ──────────────────────────────────────────────────
function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.innerText = text;
}

function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
