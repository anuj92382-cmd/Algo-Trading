/**
 * reversals.js - Real-Time Open Reversals Screener Controller
 * Handles Up Side (Dip & Surge) and Down Side (Rally & Dump) intraday screener
 * with Previous Day Cross (Crossover/Crossdown) detection
 */

let _revTab = 'UP';           // 'UP' | 'DOWN'
let _revData = null;          // Raw response cache
let _revAutoTimer = null;     // Auto-refresh interval
let _revLoadedOnce = false;   // Lazy-load flag

// ─── INITIALIZATION ──────────────────────────────────────────
function initReversalsPage() {
    if (!_revLoadedOnce) {
        loadReversals();
    }
}

// ─── TAB SWITCHING ───────────────────────────────────────────
function switchRevTab(tab) {
    if (_revTab === tab) return;
    _revTab = tab;

    const btnUp = document.getElementById('tab-btn-up');
    const btnDown = document.getElementById('tab-btn-down');
    const titleEl = document.getElementById('rev-active-tab-title');

    if (tab === 'UP') {
        if (btnUp) btnUp.classList.add('active');
        if (btnDown) btnDown.classList.remove('active');
        if (titleEl) titleEl.innerHTML = '🚀 Up Side Reversals (Open &gt; Low &amp; LTP &gt; Open)';
    } else {
        if (btnDown) btnDown.classList.add('active');
        if (btnUp) btnUp.classList.remove('active');
        if (titleEl) titleEl.innerHTML = '📉 Down Side Reversals (Open &lt; High &amp; LTP &lt; Open)';
    }

    renderTableHeader();
    applyRevClientFilters();
}

// ─── TABLE HEADER RENDER ─────────────────────────────────────
function renderTableHeader() {
    const thead = document.getElementById('rev-table-head');
    if (!thead) return;

    if (_revTab === 'UP') {
        thead.innerHTML = `
            <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>Prev ₹</th>
                <th>Open ₹</th>
                <th>Low (Dip %)</th>
                <th>High ₹</th>
                <th>LTP ₹</th>
                <th>Gain vs Open %</th>
                <th>Recovery %</th>
                <th>Day Chg %</th>
                <th>Prev Cross</th>
                <th style="min-width:140px">Intraday Position</th>
                <th>Volume</th>
                <th>Actions</th>
            </tr>
        `;
    } else {
        thead.innerHTML = `
            <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>Prev ₹</th>
                <th>Open ₹</th>
                <th>High (Rally %)</th>
                <th>Low ₹</th>
                <th>LTP ₹</th>
                <th>Drop vs Open %</th>
                <th>Fall %</th>
                <th>Day Chg %</th>
                <th>Prev Cross</th>
                <th style="min-width:140px">Intraday Position</th>
                <th>Volume</th>
                <th>Actions</th>
            </tr>
        `;
    }
}

// ─── LOAD REVERSALS DATA ─────────────────────────────────────
async function loadReversals() {
    const universe = document.getElementById('rev-universe')?.value || 'all_stocks';
    const refreshBtn = document.getElementById('rev-refresh-btn');
    const tbody = document.getElementById('rev-table-body');
    const statusEl = document.getElementById('rev-table-status');

    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '⏳ Scanning...';
    }
    if (statusEl) statusEl.textContent = 'Scanning market quotes...';

    if (!_revData && tbody) {
        tbody.innerHTML = '<tr><td colspan="14" class="empty">⏳ Scanning universe for open reversals... Please wait.</td></tr>';
    }

    try {
        const res = await api(`/api/market/reversals?universe=${universe}&min_dip=0&min_rally=0`);
        if (!res || !res.success) {
            const err = res?.error || 'Server error';
            if (tbody) tbody.innerHTML = `<tr><td colspan="14" class="empty red">❌ ${err}</td></tr>`;
            if (statusEl) statusEl.textContent = 'Error loading data';
            return;
        }

        _revData = res;
        _revLoadedOnce = true;

        const upFno = (res.up_fno_count !== undefined) ? res.up_fno_count : (res.up_side || []).filter(x => x.is_fno).length;
        const downFno = (res.down_fno_count !== undefined) ? res.down_fno_count : (res.down_side || []).filter(x => x.is_fno).length;
        const totalFno = (res.total_fno_count !== undefined) ? res.total_fno_count : (upFno + downFno);

        // Update counts and metadata
        setText('rev-up-count', res.up_count || 0);
        setText('rev-down-count', res.down_count || 0);
        setText('rev-up-crossed-badge', `⚡ ${res.up_crossed_count || 0} Crossed • ${res.up_near_count || 0} Near ⚠️ • 🎯 ${upFno} F&O`);
        setText('rev-down-crossed-badge', `⚡ ${res.down_crossed_count || 0} Crossed • ${res.down_near_count || 0} Near ⚠️ • 🎯 ${downFno} F&O`);
        setText('rev-stat-up-count', res.up_count || 0);
        setText('rev-stat-down-count', res.down_count || 0);
        setText('rev-stat-fno-count', `${totalFno} (${upFno} Up / ${downFno} Dn)`);
        setText('rev-stat-total-scanned', res.total_scanned || 0);
        setText('rev-timestamp', res.timestamp || '--:--:--');

        // Sidebar badge
        const badge = document.getElementById('reversals-badge');
        if (badge) {
            const totalReversals = (res.up_count || 0) + (res.down_count || 0);
            badge.textContent = totalReversals;
        }

        // Top Bull / Top Bear recovery
        const topBull = (res.up_side && res.up_side.length > 0) ? res.up_side[0] : null;
        const topBear = (res.down_side && res.down_side.length > 0) ? res.down_side[0] : null;

        if (topBull) {
            setText('rev-stat-top-bull', `${topBull.symbol} (+${topBull.recovery_from_low_pct.toFixed(2)}%)`);
        } else {
            setText('rev-stat-top-bull', '--');
        }

        if (topBear) {
            setText('rev-stat-top-bear', `${topBear.symbol} (-${topBear.fall_from_high_pct.toFixed(2)}%)`);
        } else {
            setText('rev-stat-top-bear', '--');
        }

        if (statusEl) {
            statusEl.textContent = `Scanned ${res.total_scanned} stocks • ${res.up_count} Up (${upFno} F&O) / ${res.down_count} Down (${downFno} F&O)`;
        }

        applyRevClientFilters();
    } catch (e) {
        console.error('Error in loadReversals:', e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="14" class="empty red">❌ Failed to fetch reversals: ${e.message}</td></tr>`;
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = '🔄 Scan Now';
        }
    }
}

// ─── CLIENT FILTER & SORT ────────────────────────────────────
function applyRevClientFilters() {
    if (!_revData) return;

    const rawList = (_revTab === 'UP') ? (_revData.up_side || []) : (_revData.down_side || []);
    const minPct = parseFloat(document.getElementById('rev-min-pct')?.value || '0');
    const prevFilter = document.getElementById('rev-prev-filter')?.value || 'all';
    const fnoFilter = document.getElementById('rev-fno-filter')?.value || 'all';
    const sortBy = document.getElementById('rev-sort-by')?.value || 'crossed_first';
    const searchQuery = (document.getElementById('rev-search')?.value || '').trim().toUpperCase();

    // 1. Filter
    let filtered = rawList.filter(item => {
        // Min dip/rally threshold
        if (_revTab === 'UP') {
            if (item.dip_pct < minPct) return false;
        } else {
            if (item.rally_pct < minPct) return false;
        }

        // Previous Day Filter
        if (prevFilter === 'crossed') {
            if (!item.crossed_break && !item.crossed_prev_day) return false;
        } else if (prevFilter === 'near') {
            if (!item.near_break) return false;
        } else if (prevFilter === 'trend') {
            if (_revTab === 'UP' && !item.is_above_prev_day) return false;
            if (_revTab === 'DOWN' && !item.is_below_prev_day) return false;
        }

        // F&O Filter
        if (fnoFilter === 'fno_only' && !item.is_fno) return false;
        if (fnoFilter === 'non_fno' && item.is_fno) return false;

        // Search text
        if (searchQuery) {
            const sym = (item.symbol || '').toUpperCase();
            const name = (item.name || '').toUpperCase();
            if (!sym.includes(searchQuery) && !name.includes(searchQuery)) return false;
        }

        return true;
    });

    // 2. Sort
    filtered.sort((a, b) => {
        if (sortBy === 'crossed_first') {
            // Crossed prev day items first
            if (b.crossed_prev_day !== a.crossed_prev_day) {
                return (b.crossed_prev_day ? 1 : 0) - (a.crossed_prev_day ? 1 : 0);
            }
            // Secondary sort: move vs open
            if (_revTab === 'UP') {
                return (b.gain_vs_open_pct || 0) - (a.gain_vs_open_pct || 0);
            } else {
                return (b.drop_vs_open_pct || 0) - (a.drop_vs_open_pct || 0);
            }
        }
        if (sortBy === 'gain_drop') {
            if (_revTab === 'UP') {
                return (b.gain_vs_open_pct || 0) - (a.gain_vs_open_pct || 0);
            } else {
                return (b.drop_vs_open_pct || 0) - (a.drop_vs_open_pct || 0);
            }
        }
        if (sortBy === 'recovery') {
            if (_revTab === 'UP') {
                return (b.recovery_from_low_pct || 0) - (a.recovery_from_low_pct || 0);
            } else {
                return (b.fall_from_high_pct || 0) - (a.fall_from_high_pct || 0);
            }
        }
        if (sortBy === 'dip_rally') {
            if (_revTab === 'UP') {
                return (b.dip_pct || 0) - (a.dip_pct || 0);
            } else {
                return (b.rally_pct || 0) - (a.rally_pct || 0);
            }
        }
        if (sortBy === 'day_change') {
            if (_revTab === 'UP') {
                return (b.change_pct || 0) - (a.change_pct || 0);
            } else {
                return (a.change_pct || 0) - (b.change_pct || 0);
            }
        }
        if (sortBy === 'volume') {
            return (b.volume || 0) - (a.volume || 0);
        }
        return 0;
    });

    renderReversalsTable(filtered);
}

// ─── RENDER TABLE ROWS ───────────────────────────────────────
function renderReversalsTable(list) {
    const tbody = document.getElementById('rev-table-body');
    if (!tbody) return;

    if (!list || list.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="14" class="empty">
                    Koi stock nahi mila is filter criteria ke saath.<br>
                    <small style="color:var(--text3)">Try switching "Prev Day Filter" to "All Reversals" ya search clear karo.</small>
                </td>
            </tr>
        `;
        return;
    }

    const html = list.map((item, idx) => {
        const rank = idx + 1;
        const sym = item.symbol;
        const ltp = item.ltp || 0;
        const open = item.open || 0;
        const high = item.high || 0;
        const low = item.low || 0;
        const prev = item.prev_close || 0;
        const dayChg = (item.change_pct !== undefined) ? item.change_pct : (item.day_change_pct || 0);
        const volStr = (typeof fmtVol === 'function') ? fmtVol(item.volume || 0) : (item.volume || 0);

        // Day Change styling
        const chgSign = dayChg > 0 ? '+' : '';
        const chgCls = dayChg > 0 ? 'green' : dayChg < 0 ? 'red' : 'dim';
        const chgArrow = dayChg > 0 ? '▲' : dayChg < 0 ? '▼' : '─';

        // Intraday Range Meter (Low to High)
        const totalSpan = Math.max(0.01, high - low);
        const openPct = Math.min(100, Math.max(0, ((open - low) / totalSpan) * 100));
        const ltpPct = Math.min(100, Math.max(0, ((ltp - low) / totalSpan) * 100));
        const prevPct = (prev > 0) ? Math.min(100, Math.max(0, ((prev - low) / totalSpan) * 100)) : -10;

        // Row highlighting: Light Yellow blink if near break, Light Green if crossed break
        let rowClass = '';
        if (item.near_break) {
            rowClass = 'row-near-break';
        } else if (item.crossed_break) {
            rowClass = 'row-crossed-break';
        }

        let meterHTML = '';
        if (_revTab === 'UP') {
            meterHTML = `
                <div class="rev-meter" title="Low: ₹${low.toFixed(2)} | Prev: ₹${prev.toFixed(2)} | Open: ₹${open.toFixed(2)} | LTP: ₹${ltp.toFixed(2)} | High: ₹${high.toFixed(2)}">
                    <div class="rev-meter-track">
                        <div class="rev-meter-fill green" style="left:${openPct.toFixed(1)}%;width:${Math.max(2, ltpPct - openPct).toFixed(1)}%"></div>
                        ${prevPct >= 0 && prevPct <= 100 ? `<div class="rev-meter-pin prev" style="left:${prevPct.toFixed(1)}%" title="Prev Close: ₹${prev.toFixed(2)}"></div>` : ''}
                        <div class="rev-meter-pin open" style="left:${openPct.toFixed(1)}%" title="Open: ₹${open.toFixed(2)}"></div>
                        <div class="rev-meter-pin ltp green" style="left:${ltpPct.toFixed(1)}%" title="LTP: ₹${ltp.toFixed(2)}"></div>
                    </div>
                    <div class="rev-meter-labels">
                        <span>L: ₹${low.toFixed(0)}</span>
                        <span>H: ₹${high.toFixed(0)}</span>
                    </div>
                </div>
            `;
        } else {
            meterHTML = `
                <div class="rev-meter" title="Low: ₹${low.toFixed(2)} | LTP: ₹${ltp.toFixed(2)} | Prev: ₹${prev.toFixed(2)} | Open: ₹${open.toFixed(2)} | High: ₹${high.toFixed(2)}">
                    <div class="rev-meter-track">
                        <div class="rev-meter-fill red" style="left:${ltpPct.toFixed(1)}%;width:${Math.max(2, openPct - ltpPct).toFixed(1)}%"></div>
                        ${prevPct >= 0 && prevPct <= 100 ? `<div class="rev-meter-pin prev" style="left:${prevPct.toFixed(1)}%" title="Prev Close: ₹${prev.toFixed(2)}"></div>` : ''}
                        <div class="rev-meter-pin open" style="left:${openPct.toFixed(1)}%" title="Open: ₹${open.toFixed(2)}"></div>
                        <div class="rev-meter-pin ltp red" style="left:${ltpPct.toFixed(1)}%" title="LTP: ₹${ltp.toFixed(2)}"></div>
                    </div>
                    <div class="rev-meter-labels">
                        <span>L: ₹${low.toFixed(0)}</span>
                        <span>H: ₹${high.toFixed(0)}</span>
                    </div>
                </div>
            `;
        }

        if (_revTab === 'UP') {
            const dipPct = (item.dip_pct || 0).toFixed(2);
            const gainVsOpen = (item.gain_vs_open_pct || 0).toFixed(2);
            const recoveryPct = (item.recovery_from_low_pct || 0).toFixed(2);

            // Previous Day crossover / near break badge
            let crossBadge = '';
            if (item.crossed_break) {
                crossBadge = `<span class="badge-pill green" title="Crossed above Previous Day High!">🔥 CROSSED PDH</span>`;
            } else if (item.near_break) {
                crossBadge = `<span class="badge-pill yellow blink" title="About to break Previous Day High! (${item.break_dist_pct}% away)">⚠️ NEAR BREAK (${item.break_dist_pct}%)</span>`;
            } else if (item.crossed_prev_day) {
                crossBadge = `<span class="badge-pill green" title="Crossed above Previous Day Close!">⚡ Crossed Up</span>`;
            } else if (item.is_above_prev_day) {
                crossBadge = `<span class="badge-mini green" title="Trading above Previous Day">▲ Above</span>`;
            } else {
                crossBadge = `<span class="badge-mini dim" title="Still below Previous Day">▼ Below</span>`;
            }

            // Targets calculation for Quick Order
            const risk = Math.max(0.5, ltp - low);
            const t1 = (ltp + risk * 1.5).toFixed(2);
            const t2 = (ltp + risk * 2.5).toFixed(2);

            const displayPrev = (item.prev_high && item.prev_high > 0) ? item.prev_high : prev;
            const prevLabel = (item.prev_high && item.prev_high > 0) ? 'PDH' : 'Close';

            return `
                <tr class="${rowClass}">
                    <td class="dim">${rank}</td>
                    <td>
                        <b>${sym}</b>
                        ${item.is_fno ? '<span class="badge-mini purple" style="margin-left:4px" title="NSE F&O Contract Available">🎯 F&O</span>' : ''}
                        ${item.crossed_break ? '<span class="badge-mini green" style="margin-left:4px" title="Crossed PDH!">🔥</span>' : (item.near_break ? '<span class="badge-mini yellow blink" style="margin-left:4px" title="Near Breakout!">⚡</span>' : '')}
                        <div class="dim" style="font-size:10px;max-width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${item.name || ''}</div>
                    </td>
                    <td class="dim" title="${prevLabel}: ₹${displayPrev.toFixed(2)}">
                        <b>₹${displayPrev > 0 ? displayPrev.toFixed(2) : '--'}</b>
                        <div style="font-size:9px;color:var(--text3)">${prevLabel}</div>
                    </td>
                    <td>₹${open.toFixed(2)}</td>
                    <td>
                        ₹${low.toFixed(2)}
                        <span class="badge-mini red">-${dipPct}%</span>
                    </td>
                    <td class="dim">₹${high.toFixed(2)}</td>
                    <td><b>₹${ltp.toFixed(2)}</b></td>
                    <td>
                        <span class="green"><b>+${gainVsOpen}%</b></span>
                    </td>
                    <td>
                        <span class="badge-pill green">⚡ +${recoveryPct}%</span>
                    </td>
                    <td>
                        <span class="${chgCls}"><b>${chgArrow} ${chgSign}${dayChg.toFixed(2)}%</b></span>
                    </td>
                    <td>${crossBadge}</td>
                    <td>${meterHTML}</td>
                    <td class="dim">${volStr}</td>
                    <td>
                        <div style="display:flex;gap:4px;align-items:center">
                            <button class="btn-sm btn-blue" onclick="openScannerModal('${sym}')" title="Scan with Stock Scanner">
                                🔬 Scan
                            </button>
                            <button class="btn-sm btn-green" onclick="quickOrder('${sym}', 'BUY', ${ltp}, ${low}, ${t1}, ${t2})" title="Quick Buy with SL at Low">
                                📈 BUY
                            </button>
                            <button class="btn-sm btn-add" onclick="addToWatchlist('${sym}')" title="Add to Watchlist">
                                +
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        } else {
            const rallyPct = (item.rally_pct || 0).toFixed(2);
            const dropVsOpen = (item.drop_vs_open_pct || 0).toFixed(2);
            const fallPct = (item.fall_from_high_pct || 0).toFixed(2);

            // Previous Day crossdown / near break badge
            let crossBadge = '';
            if (item.crossed_break) {
                crossBadge = `<span class="badge-pill red" title="Crossed below Previous Day Low!">💥 CROSSED PDL</span>`;
            } else if (item.near_break) {
                crossBadge = `<span class="badge-pill yellow blink" title="About to break Previous Day Low! (${item.break_dist_pct}% away)">⚠️ NEAR BREAK (${item.break_dist_pct}%)</span>`;
            } else if (item.crossed_prev_day) {
                crossBadge = `<span class="badge-pill red" title="Crossed below Previous Day Close!">⚡ Crossed Down</span>`;
            } else if (item.is_below_prev_day) {
                crossBadge = `<span class="badge-mini red" title="Trading below Previous Day">▼ Below</span>`;
            } else {
                crossBadge = `<span class="badge-mini dim" title="Still above Previous Day">▲ Above</span>`;
            }

            // Targets calculation for Quick Order
            const risk = Math.max(0.5, high - ltp);
            const t1 = (ltp - risk * 1.5).toFixed(2);
            const t2 = (ltp - risk * 2.5).toFixed(2);

            const displayPrev = (item.prev_low && item.prev_low > 0) ? item.prev_low : prev;
            const prevLabel = (item.prev_low && item.prev_low > 0) ? 'PDL' : 'Close';

            return `
                <tr class="${rowClass}">
                    <td class="dim">${rank}</td>
                    <td>
                        <b>${sym}</b>
                        ${item.is_fno ? '<span class="badge-mini purple" style="margin-left:4px" title="NSE F&O Contract Available">🎯 F&O</span>' : ''}
                        ${item.crossed_break ? '<span class="badge-mini red" style="margin-left:4px" title="Crossed PDL!">💥</span>' : (item.near_break ? '<span class="badge-mini yellow blink" style="margin-left:4px" title="Near Breakdown!">⚡</span>' : '')}
                        <div class="dim" style="font-size:10px;max-width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${item.name || ''}</div>
                    </td>
                    <td class="dim" title="${prevLabel}: ₹${displayPrev.toFixed(2)}">
                        <b>₹${displayPrev > 0 ? displayPrev.toFixed(2) : '--'}</b>
                        <div style="font-size:9px;color:var(--text3)">${prevLabel}</div>
                    </td>
                    <td>₹${open.toFixed(2)}</td>
                    <td>
                        ₹${high.toFixed(2)}
                        <span class="badge-mini green">+${rallyPct}%</span>
                    </td>
                    <td class="dim">₹${low.toFixed(2)}</td>
                    <td><b>₹${ltp.toFixed(2)}</b></td>
                    <td>
                        <span class="red"><b>-${dropVsOpen}%</b></span>
                    </td>
                    <td>
                        <span class="badge-pill red">🔻 -${fallPct}%</span>
                    </td>
                    <td>
                        <span class="${chgCls}"><b>${chgArrow} ${chgSign}${dayChg.toFixed(2)}%</b></span>
                    </td>
                    <td>${crossBadge}</td>
                    <td>${meterHTML}</td>
                    <td class="dim">${volStr}</td>
                    <td>
                        <div style="display:flex;gap:4px;align-items:center">
                            <button class="btn-sm btn-blue" onclick="openScannerModal('${sym}')" title="Scan with Stock Scanner">
                                🔬 Scan
                            </button>
                            <button class="btn-sm btn-red" onclick="quickOrder('${sym}', 'SELL', ${ltp}, ${high}, ${t1}, ${t2})" title="Quick Sell with SL at High">
                                📉 SELL
                            </button>
                            <button class="btn-sm btn-add" onclick="addToWatchlist('${sym}')" title="Add to Watchlist">
                                +
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }
    }).join('');

    tbody.innerHTML = html;
}

// ─── AUTO REFRESH ────────────────────────────────────────────
function toggleRevAutoRefresh(enable) {
    if (_revAutoTimer) {
        clearInterval(_revAutoTimer);
        _revAutoTimer = null;
    }

    if (enable) {
        showToast('🔄 Auto-refresh enabled (every 10 seconds)', 'toast-info');
        _revAutoTimer = setInterval(loadReversals, 10000);
    } else {
        showToast('⏹️ Auto-refresh paused', 'toast-info');
    }
}

// ─── STOCK SCANNER MODAL (FOR REVERSALS TAB) ─────────────────
let _currentScanSymbol = null;

async function openScannerModal(symbol) {
    _currentScanSymbol = symbol;
    const modal = document.getElementById('rev-scan-modal');
    if (modal) modal.style.display = 'flex';

    setText('rev-scan-modal-title', `🔬 ${symbol} — Technical Analysis`);
    setText('rev-scan-modal-sub', 'Fetching indicators: RSI, MACD, EMA 9/21/50, Supertrend, VWAP, ADX...');
    setHTML('rev-scan-modal-body', `
        <div class="sc-modal-loading" style="padding:36px;text-align:center">
            <div style="font-size:32px;margin-bottom:12px">⏳</div>
            <b style="color:var(--text);font-size:15px">${symbol} ka Stock Scanner analysis ho raha hai...</b>
            <p style="color:var(--text3);font-size:12px;margin-top:6px">Historical candles aur technical indicators calculate kiye ja rahe hain</p>
        </div>
    `);

    await reRunScanModal();
}

async function reRunScanModal() {
    if (!_currentScanSymbol) return;

    const tf = document.getElementById('rev-scan-modal-tf')?.value || 'day';
    const bodyEl = document.getElementById('rev-scan-modal-body');
    if (!bodyEl) return;

    try {
        const res = await api('/api/scanner/analyse', 'POST', {
            symbol: _currentScanSymbol,
            timeframe: tf,
            min_score: 1
        });

        if (!res) {
            setHTML('rev-scan-modal-body', '<div class="sc-modal-error" style="padding:24px;text-align:center">❌ Server error: Response nahi mila</div>');
            return;
        }

        if (res.success && res.signal) {
            setText('rev-scan-modal-title', `🔬 ${res.signal.symbol} — ${res.signal.signal_type || 'ANALYSIS'}`);
            setText('rev-scan-modal-sub', `Timeframe: ${tf.toUpperCase()} | Score: ${res.signal.score}/10 | Confidence: ${res.signal.confidence}`);

            if (typeof signalCard === 'function') {
                setHTML('rev-scan-modal-body', signalCard(res.signal));
            } else {
                setHTML('rev-scan-modal-body', `
                    <div class="sc-card ${res.signal.direction === 'LONG' ? 'long' : 'short'}">
                        <div style="padding:16px">
                            <h3>${res.signal.symbol} - ${res.signal.direction}</h3>
                            <p>Score: ${res.signal.score}/10</p>
                            <p>LTP: ₹${res.signal.ltp}</p>
                            <p>RSI: ${res.signal.rsi?.toFixed(1)} | ADX: ${res.signal.adx?.toFixed(1)}</p>
                        </div>
                    </div>
                `);
            }
        } else {
            const errMsg = res.error || 'Signal calculate nahi ho paya';
            setHTML('rev-scan-modal-body', `
                <div class="sc-modal-nosig" style="padding:30px;text-align:center">
                    <div style="font-size:36px;margin-bottom:10px">⚠️</div>
                    <b style="color:var(--yellow);font-size:15px">${_currentScanSymbol} — Notice</b>
                    <p style="color:var(--text2);margin-top:8px;font-size:13px;line-height:1.5">
                        ${errMsg}<br>
                        <span style="color:var(--text3);font-size:11px">Tip: Upar dropdown se alag timeframe (5m, 15m, 60m, day) select karke dobara try kar sakte hain.</span>
                    </p>
                </div>
            `);
        }
    } catch (err) {
        setHTML('rev-scan-modal-body', `<div class="sc-modal-error" style="padding:20px;text-align:center">❌ Network Error: ${err.message}</div>`);
    }
}

function closeRevScanModal() {
    const modal = document.getElementById('rev-scan-modal');
    if (modal) modal.style.display = 'none';
    _currentScanSymbol = null;
}

// Backdrop click close
document.addEventListener('click', e => {
    const modal = document.getElementById('rev-scan-modal');
    if (modal && e.target === modal) closeRevScanModal();
});

