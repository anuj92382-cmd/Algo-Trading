/**
 * mcx.js - MCX Commodity Algo Trading Controller
 * Handles live quotes, commodities cards, strategies, and paper execution
 */

let _mcxTimer = null;
let _mcxDataCache = null;

function initMcxPage() {
    fetchMcxStatus();
    if (_mcxTimer) clearInterval(_mcxTimer);
    _mcxTimer = setInterval(fetchMcxStatus, 3000);
}

async function fetchMcxStatus() {
    try {
        const res = await fetch('/api/mcx/status');
        const data = await res.json();
        if (!data.success) return;

        _mcxDataCache = data;
        renderMcxHeader(data);
        renderMcxKpis(data);
        renderMcxCards(data.commodities || []);
        renderMcxPositions(data.positions || []);
        renderMcxTrades(data.closed_trades || []);
        renderMcxLogs(data.logs || []);
    } catch (e) {
        console.debug('MCX fetch error:', e);
    }
}

function renderMcxHeader(data) {
    const isRunning = data.status === 'RUNNING';
    const isPaper = data.mode === 'PAPER';

    // Status Badge
    const statusBadge = document.getElementById('mcx-bot-status-badge');
    if (statusBadge) {
        statusBadge.className = `badge-pill ${isRunning ? 'green' : 'yellow'}`;
        statusBadge.innerHTML = isRunning ? '● ACTIVE' : '● PAUSED';
    }

    // Toggle Button
    const toggleBtn = document.getElementById('mcx-bot-toggle-btn');
    if (toggleBtn) {
        toggleBtn.className = `btn btn-algo-ctrl ${isRunning ? 'btn-yellow' : 'btn-green'}`;
        toggleBtn.innerHTML = isRunning ? '⏸ Pause Bot' : '▶ Start Bot';
    }

    // Mode Badge
    const modeBadge = document.getElementById('mcx-mode-badge');
    if (modeBadge) {
        modeBadge.className = `badge-pill ${isPaper ? 'purple' : 'red'}`;
        modeBadge.innerHTML = isPaper ? '📄 PAPER (5X MARGIN)' : '🔴 LIVE BROKER';
    }

    // Mode Buttons
    const paperBtn = document.getElementById('mcx-mode-paper-btn');
    const liveBtn = document.getElementById('mcx-mode-live-btn');
    if (paperBtn) paperBtn.classList.toggle('active', isPaper);
    if (liveBtn) liveBtn.classList.toggle('active', !isPaper);

    // Session Timing
    const sess = data.session || {};
    const sessionBadge = document.getElementById('mcx-session-badge');
    if (sessionBadge) {
        sessionBadge.className = `badge-pill ${sess.is_open ? 'cyan' : 'red'}`;
        sessionBadge.innerHTML = `⏰ ${(sess.session_name || 'MARKET HOURS').toUpperCase()} (09:00 AM – 11:30 PM)`;
    }
}

function renderMcxKpis(data) {
    const stats = data.stats || {};
    const todayPnl = stats.today_pnl || 0;
    const realizedPnl = stats.realized_pnl || 0;

    const pnlEl = document.getElementById('mcx-kpi-today-pnl');
    if (pnlEl) {
        pnlEl.className = `algo-kpi-val ${todayPnl >= 0 ? 'green' : 'red'}`;
        pnlEl.textContent = `${todayPnl >= 0 ? '+' : ''}₹${todayPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    const realEl = document.getElementById('mcx-kpi-realized-pnl');
    if (realEl) {
        realEl.className = `algo-kpi-val ${realizedPnl >= 0 ? 'green' : 'red'}`;
        realEl.textContent = `${realizedPnl >= 0 ? '+' : ''}₹${realizedPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    const tradesEl = document.getElementById('mcx-kpi-trades-count');
    if (tradesEl) tradesEl.textContent = `${stats.win_count || 0}W / ${stats.loss_count || 0}L (${stats.win_rate || 0}%)`;

    const posCount = (data.positions || []).length;
    const posEl = document.getElementById('mcx-kpi-positions-count');
    if (posEl) posEl.textContent = posCount;

    const mktStatusEl = document.getElementById('mcx-kpi-market-status');
    if (mktStatusEl) {
        const isOpen = (data.session || {}).is_open;
        mktStatusEl.className = `algo-kpi-val ${isOpen ? 'green' : 'red'}`;
        mktStatusEl.textContent = isOpen ? 'OPEN (Till 11:30 PM)' : 'CLOSED';
    }
}

async function setMcxMode(mode) {
    try {
        const res = await fetch('/api/mcx/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: mode })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Switched to ${data.mode} Trading Mode`, 'info');
            fetchMcxStatus();
        }
    } catch (e) {
        showToast('Failed to switch MCX mode', 'error');
    }
}

function renderMcxCards(commodities) {
    const grid = document.getElementById('mcx-commodities-grid');
    if (!grid) return;

    if (!commodities || commodities.length === 0) {
        grid.innerHTML = '<div class="empty">No MCX commodities available</div>';
        return;
    }

    grid.innerHTML = commodities.map(c => {
        const isUp = c.net_change >= 0;
        const chgColor = isUp ? 'green' : 'red';
        const chgSign = isUp ? '+' : '';
        const priceStr = c.ltp > 0 ? `₹${c.ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
        
        let sigClass = 'grey';
        let sigIcon = '⏳';
        if (c.signal_side === 'BUY') { sigClass = 'green'; sigIcon = '🟢'; }
        else if (c.signal_side === 'SELL') { sigClass = 'red'; sigIcon = '🔴'; }

        const isEnabled = c.enabled !== false;
        return `
            <div class="algo-strat-card ${isEnabled ? 'active-strat' : 'disabled-strat'}" style="border-top: 3px solid ${isUp ? '#10b981' : '#ef4444'}">
                <div class="strat-card-header">
                    <div class="strat-title-group">
                        <span class="strat-icon" style="font-size:26px">${c.icon}</span>
                        <div>
                            <div class="strat-name" style="font-size:15px;display:flex;align-items:center;gap:6px">
                                <strong>${c.name}</strong>
                                <span class="badge-mini blue">${c.tradingsymbol}</span>
                            </div>
                            <div style="font-size:11px;color:var(--text3);margin-top:2px">
                                Lot: ${c.lot_size} ${c.unit} • Expiry: ${c.expiry}
                            </div>
                        </div>
                    </div>
                    <div style="display:flex;align-items:center;gap:12px">
                        <div style="text-align:right">
                            <div style="font-size:18px;font-weight:800;font-family:'JetBrains Mono',monospace;color:#f8fafc">
                                ${priceStr}
                            </div>
                            <div style="font-size:11px;font-weight:700;color:${isUp ? '#34d399' : '#f87171'}">
                                ${chgSign}${c.net_change}%
                            </div>
                        </div>
                        <label class="algo-switch" title="Toggle Auto-Trading for ${c.name}">
                            <input type="checkbox" ${isEnabled ? 'checked' : ''} onchange="toggleCommodity('${c.commodity}', this.checked)">
                            <span class="algo-slider"></span>
                        </label>
                    </div>
                </div>

                <div class="strat-params-grid" style="grid-template-columns: repeat(4, 1fr);margin-top:8px">
                    <div class="strat-param">
                        <span class="param-lbl">Target (T1)</span>
                        <span class="param-val green">+${c.target_1_pct}%</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">Stop Loss</span>
                        <span class="param-val red">-${c.sl_pct}%</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">High / Low</span>
                        <span class="param-val">₹${c.high.toLocaleString('en-IN')}</span>
                    </div>
                    <div class="strat-param">
                        <span class="param-lbl">Volume</span>
                        <span class="param-val cyan">${(c.volume || 0).toLocaleString('en-IN')}</span>
                    </div>
                </div>

                <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:6px;padding:8px 10px;margin-top:10px;display:flex;align-items:center;justify-content:space-between">
                    <div>
                        <div style="font-size:10px;color:var(--text3);text-transform:uppercase;font-weight:700">Autonomous Strategy</div>
                        <div style="font-size:12px;font-weight:600;color:#93c5fd;margin-top:2px">
                            ${c.strategy}
                        </div>
                    </div>
                    <span class="badge-pill ${sigClass}" style="font-size:10.5px">
                        ${sigIcon} ${c.signal_side}
                    </span>
                </div>

                <div class="strat-card-footer" style="margin-top:10px;padding-top:8px">
                    <div style="font-size:11px;color:var(--text3)">
                        Auto-Pilot: <strong style="color:${isEnabled ? '#4ade80' : '#f87171'}">${isEnabled ? '● Active' : '○ Disabled'}</strong>
                    </div>
                    <div style="display:flex;gap:6px">
                        <button class="btn btn-xs btn-green" onclick="quickOrderMcx('${c.commodity}', 'BUY')" title="Paper Buy ${c.name}">
                            🟢 Buy ${c.lot_size} Lot
                        </button>
                        <button class="btn btn-xs btn-red" onclick="quickOrderMcx('${c.commodity}', 'SELL')" title="Paper Sell ${c.name}">
                            🔴 Sell ${c.lot_size} Lot
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function toggleCommodity(commKey, isEnabled) {
    try {
        const res = await fetch('/api/mcx/commodity/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ commodity: commKey, enabled: isEnabled })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`${commKey} Auto-Trading ${isEnabled ? 'Enabled' : 'Disabled'}!`, 'info');
            fetchMcxStatus();
        }
    } catch (e) {
        showToast('Failed to toggle commodity setting', 'error');
    }
}

async function scanMcxNow() {
    try {
        const res = await fetch('/api/mcx/scan_now', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast('⚡ MCX Auto Scan Triggered!', 'success');
            setTimeout(fetchMcxStatus, 1000);
        }
    } catch (e) {
        showToast('Failed to trigger MCX scan', 'error');
    }
}

function renderMcxPositions(positions) {
    const tbody = document.getElementById('mcx-positions-tbody');
    if (!tbody) return;

    if (!positions || positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty">No active MCX commodity positions</td></tr>';
        return;
    }

    tbody.innerHTML = positions.map(p => {
        const isWin = p.pnl >= 0;
        const pnlColor = isWin ? 'green' : 'red';
        const pnlSign = isWin ? '+' : '';

        return `
            <tr>
                <td><strong>${p.commodity}</strong> <span style="font-size:10px;color:var(--text3)">(${p.tradingsymbol})</span></td>
                <td><span class="badge-mini ${p.side === 'BUY' ? 'green' : 'red'}">${p.side}</span></td>
                <td><strong>${p.quantity}</strong></td>
                <td>₹${p.entry_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                <td><strong>₹${p.current_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong></td>
                <td><span style="color:#34d399">₹${(p.target || 0).toLocaleString('en-IN')}</span></td>
                <td><span style="color:#f87171">₹${(p.stop_loss || 0).toLocaleString('en-IN')}</span></td>
                <td class="${pnlColor}">
                    <strong>${pnlSign}₹${p.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong>
                    <div style="font-size:10px">${pnlSign}${p.pnl_pct}%</div>
                </td>
                <td style="font-size:11px;color:var(--text3)">${p.entry_time}</td>
                <td>
                    <button class="btn btn-xs btn-red" onclick="exitMcxPos('${p.id}')">Exit</button>
                </td>
            </tr>
        `;
    }).join('');
}

function renderMcxTrades(trades) {
    const tbody = document.getElementById('mcx-trades-tbody');
    if (!tbody) return;

    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty">No closed commodity trades today</td></tr>';
        return;
    }

    tbody.innerHTML = trades.map(t => {
        const isWin = t.pnl >= 0;
        return `
            <tr>
                <td><strong>${t.commodity}</strong></td>
                <td><span class="badge-mini ${t.side === 'BUY' ? 'green' : 'red'}">${t.side}</span></td>
                <td>${t.quantity}</td>
                <td>₹${t.entry_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                <td>₹${t.exit_price.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                <td class="${isWin ? 'green' : 'red'}"><strong>${isWin ? '+' : ''}₹${t.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong></td>
                <td><span class="badge-mini ${isWin ? 'green' : 'red'}">${t.status}</span></td>
                <td style="font-size:11px">${t.reason}</td>
                <td style="font-size:11px;color:var(--text3)">${t.exit_time}</td>
            </tr>
        `;
    }).join('');
}

function renderMcxLogs(logs) {
    const consoleEl = document.getElementById('mcx-logs-console');
    if (!consoleEl) return;

    if (!logs || logs.length === 0) {
        consoleEl.innerHTML = '<div class="algo-log-entry" style="color:var(--text3)">No MCX events recorded yet.</div>';
        return;
    }

    consoleEl.innerHTML = logs.map(l => `
        <div class="algo-log-entry">
            <span class="algo-log-time">[${l.time}]</span>
            <span class="algo-log-tag ${l.tag.toLowerCase()}">${l.tag}</span>
            <span class="algo-log-title">${l.title}</span>
            ${l.details ? `<span class="algo-log-details">— ${l.details}</span>` : ''}
        </div>
    `).join('');
}

async function toggleMcxBot() {
    try {
        const res = await fetch('/api/mcx/toggle', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`MCX Bot ${data.status}!`, 'info');
            fetchMcxStatus();
        }
    } catch (e) {
        showToast('Failed to toggle MCX bot', 'error');
    }
}

async function quickOrderMcx(commodity, side) {
    try {
        const res = await fetch('/api/mcx/order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ commodity: commodity, side: side, quantity: 1 })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`⚡ ${side} Order placed for ${commodity}!`, 'success');
            fetchMcxStatus();
        } else {
            showToast(data.error || 'Failed to place order', 'error');
        }
    } catch (e) {
        showToast('Error placing MCX order', 'error');
    }
}

async function exitMcxPos(posId) {
    try {
        const res = await fetch('/api/mcx/exit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pos_id: posId })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Position closed!', 'success');
            fetchMcxStatus();
        } else {
            showToast(data.error || 'Failed to exit position', 'error');
        }
    } catch (e) {
        showToast('Error exiting MCX position', 'error');
    }
}
