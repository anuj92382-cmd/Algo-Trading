/**
 * config.js - Configuration, Trading Mode Switcher, Paper Sandbox & RMS Controller
 */

let _cfgCurrentMode = 'PAPER';
let _cfgSelectedMode = 'PAPER';

async function initConfigPage() {
    await Promise.allSettled([
        loadConfigPageData(),
        loadBrokerMargins(),
        loadPaperStats(),
    ]);
}

// ─── 1. LOAD MAIN CONFIG & RMS DATA ──────────────────────────
async function loadConfigPageData() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error('Failed to load system config');
        const data = await res.json();

        // 1. Trading Mode
        _cfgCurrentMode = (data.trading_mode || 'PAPER').toUpperCase();
        _cfgSelectedMode = _cfgCurrentMode;
        renderModeSelection();

        // 2. Broker Telemetry
        if (data.user_id) setText('cfg-broker-userid', data.user_id);
        if (data.user_name) setText('cfg-broker-username', data.user_name);
        
        const brokerStatusPill = document.getElementById('cfg-broker-status-pill');
        if (brokerStatusPill) {
            if (data.logged_in) {
                brokerStatusPill.className = 'badge-pill green';
                brokerStatusPill.textContent = 'CONNECTED';
            } else {
                brokerStatusPill.className = 'badge-pill red';
                brokerStatusPill.textContent = 'NOT LOGGED IN';
            }
        }

        // 3. Broker Live Margins (Direct from Zerodha Kite)
        if (data.broker_margins) {
            const eqEl = document.getElementById('cfg-broker-equity-margin');
            if (eqEl) {
                eqEl.textContent = `₹${Number(data.broker_margins.equity || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            }

            const mcxEl = document.getElementById('cfg-broker-mcx-margin');
            if (mcxEl) {
                mcxEl.textContent = `₹${Number(data.broker_margins.commodity || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            }
        }

        // 4. Paper Summary
        if (data.paper_summary) {
            renderPaperSummaryData(data.paper_summary);
        }

        // 5. RMS & Universe Fields
        if (data.universe) {
            const uniEl = document.getElementById('algo-universe-select');
            if (uniEl) uniEl.value = data.universe;
        }

        const rc = data.risk_config || {};
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el && val !== undefined && val !== null) el.value = val;
        };

        setVal('algo-rms-total-capital', rc.total_capital || data.total_capital || 2000000);
        setVal('algo-rms-max-loss', rc.max_daily_loss || 1000);
        setVal('algo-rms-max-profit', rc.max_daily_profit || 5000);
        setVal('algo-rms-max-positions', rc.max_open_positions || 4);
        setVal('algo-rms-min-winrate', rc.min_win_rate_pct || 60);
        setVal('algo-rms-min-price', rc.min_stock_price !== undefined ? rc.min_stock_price : 50);
        setVal('algo-rms-max-price', rc.max_stock_price !== undefined ? rc.max_stock_price : 3000);
        setVal('algo-rms-min-mcap', rc.min_market_cap_m !== undefined ? rc.min_market_cap_m : 100);

        // Update capital split hint
        if (typeof updateCapitalSplitHint === 'function') {
            updateCapitalSplitHint();
        }

        // Circuit breaker status
        const cbBadge = document.getElementById('algo-cb-status-badge');
        const cbAlert = document.getElementById('algo-circuit-breaker-alert');
        const cbReason = document.getElementById('algo-cb-reason');
        const cbMini = document.getElementById('algo-cb-status-badge-mini');

        if (rc.circuit_breaker_hit) {
            if (cbBadge) cbBadge.style.display = 'none';
            if (cbAlert) {
                cbAlert.style.display = 'inline-flex';
                if (cbReason) cbReason.textContent = rc.circuit_breaker_reason || 'Daily Loss Breached';
            }
            if (cbMini) {
                cbMini.className = 'badge-pill red';
                cbMini.textContent = 'TRIPPED: ' + (rc.circuit_breaker_reason || 'HALTED');
            }
        } else {
            if (cbBadge) {
                cbBadge.style.display = 'inline-block';
                cbBadge.className = 'badge-pill green';
                cbBadge.textContent = '🛡️ RMS: ARMED & PROTECTED';
            }
            if (cbAlert) cbAlert.style.display = 'none';
            if (cbMini) {
                cbMini.className = 'badge-pill green';
                cbMini.textContent = 'ARMED & PROTECTED';
            }
        }

    } catch (e) {
        console.error('Config page load error:', e);
    }
}

// ─── 2. BROKER LIVE MARGINS TELEMETRY ─────────────────────────
async function loadBrokerMargins() {
    try {
        const res = await fetch('/api/config');
        if (!res.ok) return;
        const data = await res.json();

        if (data.broker_margins) {
            const eqEl = document.getElementById('cfg-broker-equity-margin');
            if (eqEl) {
                eqEl.textContent = `₹${Number(data.broker_margins.equity || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            }

            const mcxEl = document.getElementById('cfg-broker-mcx-margin');
            if (mcxEl) {
                mcxEl.textContent = `₹${Number(data.broker_margins.commodity || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            }
        }
    } catch (e) {
        console.debug('Error loading broker margins:', e);
    }
}

// ─── 3. PAPER STATS RENDERING ─────────────────────────────────
async function loadPaperStats() {
    try {
        const res = await fetch('/api/trade/paper_positions');
        if (!res.ok) return;
        const data = await res.json();
        
        setText('cfg-paper-open-count', data.count || 0);
        setText('cfg-paper-realized-pnl', `₹${Number(data.closed_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
        
        const pnlEl = document.getElementById('cfg-paper-realized-pnl');
        if (pnlEl) {
            pnlEl.style.color = (data.closed_pnl || 0) >= 0 ? '#34d399' : '#f87171';
        }

        // Also fetch total paper margin
        const cfgRes = await fetch('/api/config');
        if (cfgRes.ok) {
            const cfg = await cfgRes.json();
            if (cfg.paper_summary) {
                renderPaperSummaryData(cfg.paper_summary);
            }
        }
    } catch (e) {
        console.debug('Error loading paper stats:', e);
    }
}

function renderPaperSummaryData(ps) {
    setText('cfg-paper-net-cap', `₹${Number(ps.net_capital || ps.total_capital || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`);
    setText('cfg-paper-used-margin', `₹${Number(ps.used_margin || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`);
    setText('cfg-paper-avail-margin', `₹${Number(ps.available_margin || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`);
    setText('cfg-paper-realized-pnl', `₹${Number(ps.closed_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
    
    if (ps.open_positions_count !== undefined) {
        setText('cfg-paper-open-count', ps.open_positions_count);
    }

    const pnlEl = document.getElementById('cfg-paper-realized-pnl');
    if (pnlEl) {
        pnlEl.style.color = (ps.closed_pnl || 0) >= 0 ? '#34d399' : '#f87171';
    }
}

// ─── 4. MODE SELECTION & SWITCHING ────────────────────────────
function selectConfigMode(mode) {
    _cfgSelectedMode = mode.toUpperCase();
    renderModeSelection();
}

function renderModeSelection() {
    const cardPaper = document.getElementById('cfg-mode-card-paper');
    const cardLive = document.getElementById('cfg-mode-card-live');
    const dotPaper = document.getElementById('cfg-paper-selected-dot');
    const dotLive = document.getElementById('cfg-live-selected-dot');
    const activePill = document.getElementById('cfg-mode-active-pill');
    const switchBtn = document.getElementById('cfg-btn-switch-mode');

    // Update active pill
    if (activePill) {
        if (_cfgCurrentMode === 'LIVE') {
            activePill.className = 'badge-pill red';
            activePill.textContent = '🔴 LIVE TRADING';
        } else {
            activePill.className = 'badge-pill blue';
            activePill.textContent = '🧪 PAPER TRADING';
        }
    }

    // Highlighting cards based on _cfgSelectedMode
    if (cardPaper && cardLive) {
        if (_cfgSelectedMode === 'PAPER') {
            cardPaper.style.borderColor = '#3b82f6';
            cardPaper.style.background = 'rgba(59, 130, 246, 0.12)';
            if (dotPaper) {
                dotPaper.textContent = (_cfgCurrentMode === 'PAPER') ? '● ACTIVE' : '● SELECTED';
                dotPaper.style.color = '#60a5fa';
            }

            cardLive.style.borderColor = 'rgba(255, 255, 255, 0.1)';
            cardLive.style.background = 'rgba(255, 255, 255, 0.03)';
            if (dotLive) {
                dotLive.textContent = (_cfgCurrentMode === 'LIVE') ? '● ACTIVE' : '○ INACTIVE';
                dotLive.style.color = '#64748b';
            }
        } else {
            cardLive.style.borderColor = '#ef4444';
            cardLive.style.background = 'rgba(239, 68, 68, 0.12)';
            if (dotLive) {
                dotLive.textContent = (_cfgCurrentMode === 'LIVE') ? '● ACTIVE' : '● SELECTED';
                dotLive.style.color = '#f87171';
            }

            cardPaper.style.borderColor = 'rgba(255, 255, 255, 0.1)';
            cardPaper.style.background = 'rgba(255, 255, 255, 0.03)';
            if (dotPaper) {
                dotPaper.textContent = (_cfgCurrentMode === 'PAPER') ? '● ACTIVE' : '○ INACTIVE';
                dotPaper.style.color = '#64748b';
            }
        }
    }

    // Switch button label
    if (switchBtn) {
        if (_cfgSelectedMode === _cfgCurrentMode) {
            switchBtn.className = 'btn btn-sm btn-grey';
            switchBtn.textContent = `✓ Already in ${_cfgCurrentMode} Mode`;
            switchBtn.disabled = true;
        } else {
            switchBtn.disabled = false;
            if (_cfgSelectedMode === 'LIVE') {
                switchBtn.className = 'btn btn-sm btn-red';
                switchBtn.textContent = '🔴 Switch to LIVE Trading';
            } else {
                switchBtn.className = 'btn btn-sm btn-blue';
                switchBtn.textContent = '🧪 Switch to PAPER Mode';
            }
        }
    }
}

async function confirmSwitchMode() {
    const targetMode = _cfgSelectedMode;
    if (targetMode === _cfgCurrentMode) return;

    if (targetMode === 'LIVE') {
        const agreed = confirm(
            '⚠️ LIVE TRADING WARNING!\n\n' +
            'Aap LIVE TRADING mode mein switch kar rahe hain.\n' +
            'Bot seedhe aapke Zerodha Kite account se real market orders place karega aur real funds use honge!\n\n' +
            'Kya aap aage badhna chahte hain?'
        );
        if (!agreed) return;
    } else {
        const agreed = confirm(
            '🧪 Switch to PAPER TRADING mode?\n\n' +
            'Paper mode virtual capital aur 5X intraday leverage simulation use karta hai (Zero real risk).'
        );
        if (!agreed) return;
    }

    try {
        const res = await fetch('/api/algo/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: targetMode })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`✅ Mode successfully switched to ${targetMode}!`, 'success');
            _cfgCurrentMode = targetMode;
            _cfgSelectedMode = targetMode;
            renderModeSelection();

            // Sync sidebar and global badges
            const sbMode = document.getElementById('sidebarMode');
            if (sbMode) {
                sbMode.textContent = targetMode;
                sbMode.style.color = targetMode === 'LIVE' ? '#f87171' : '#60a5fa';
            }

            // Refresh app status
            if (typeof fetchStatus === 'function') fetchStatus();
            if (typeof loadConfigPageData === 'function') loadConfigPageData();
        } else {
            showToast(data.error || 'Failed to switch mode', 'error');
        }
    } catch (e) {
        showToast('Error switching trading mode', 'error');
    }
}

// ─── 5. PAPER CAPITAL PRESETS ─────────────────────────────────
function setVirtualCapitalPreset(amount) {
    const capInput = document.getElementById('algo-rms-total-capital');
    if (capInput) {
        capInput.value = amount;
        if (typeof updateCapitalSplitHint === 'function') {
            updateCapitalSplitHint();
        }
    }
    // Auto save
    if (typeof saveAlgoRMS === 'function') {
        saveAlgoRMS();
    }
    showToast(`💰 Capital set to ₹${amount.toLocaleString('en-IN')}`, 'info');
}

// ─── 6. RESET PAPER PORTFOLIO ─────────────────────────────────
async function resetPaperPortfolioFromConfig() {
    if (!confirm('🗑️ Reset paper portfolio?\n\nSaare open paper positions aur order history delete ho jayenge aur P&L ₹0 ho jayega. Yeh action undo nahi ho sakta!')) {
        return;
    }

    try {
        const res = await fetch('/api/trade/paper_reset', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast('✅ Paper portfolio reset ho gaya!', 'success');
            loadPaperStats();
            if (typeof loadPaperPortfolio === 'function') {
                loadPaperPortfolio();
            }
        } else {
            showToast(data.error || 'Reset failed', 'error');
        }
    } catch (e) {
        showToast('Error resetting paper portfolio', 'error');
    }
}

// ─── 7. SAVE ALL CONFIG & RMS ─────────────────────────────────
async function saveAllConfigAndRMS() {
    // 1. If mode changed, confirm & switch
    if (_cfgSelectedMode !== _cfgCurrentMode) {
        await confirmSwitchMode();
    }

    // 2. Save RMS Rules
    if (typeof saveAlgoRMS === 'function') {
        await saveAlgoRMS();
    }
}
