/**
 * app.js - Core Dashboard Logic
 * Auto-refresh, status, P&L, positions, trades, orders
 */

const REFRESH_MS = 5000;
let _countdown   = 5;
let _botRunning  = false;

// ─── INIT ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    showPage('dashboard');
    refreshCore();
    setInterval(refreshCore, REFRESH_MS);
    setInterval(() => {
        _countdown = _countdown <= 1 ? 5 : _countdown - 1;
        setText('countdown', _countdown);
    }, 1000);
    startClock();
});

function startClock() {
    // Local clock that increments every second (synced from backend every 5s)
    let lastBackendTime = null;
    
    setInterval(() => {
        // If we have backend time, increment it locally
        if (lastBackendTime) {
            const parts = lastBackendTime.split(':');
            let h = parseInt(parts[0]);
            let m = parseInt(parts[1]);
            let s = parseInt(parts[2]);
            
            s++;
            if (s >= 60) { s = 0; m++; }
            if (m >= 60) { m = 0; h++; }
            if (h >= 24) { h = 0; }
            
            lastBackendTime = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
            setText('mktTime', lastBackendTime);
        }
    }, 1000);
    
    // Save reference so fetchStatus can update it
    window._syncClockFromBackend = (time) => { lastBackendTime = time; };
}

// ─── PAGE NAV ────────────────────────────────────────────────
function showPage(name) {
    // Pages
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const pg = document.getElementById(`page-${name}`);
    if (pg) pg.classList.add('active');

    // Nav items
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const nav = document.querySelector(`.nav-item[data-page="${name}"]`);
    if (nav) nav.classList.add('active');

    // Page title
    const titles = {
        dashboard: 'Dashboard',
        gainers:   'Top Gainers',
        losers:    'Top Losers',
        stocks:    'All Stocks',
        positions: 'Positions',
        trades:    'Trades',
        orders:    'Orders',
        scanner:   '🔬 Stock Scanner',
        sectors:   '🌡️ Sector Heatmap',
        trade:     '💹 Trade - Buy / Sell',
    };
    setText('pageTitle', titles[name] || name);

    // Lazy load
    if (name === 'gainers' || name === 'losers') loadGainersLosers();
    if (name === 'positions') fetchPositions();
    if (name === 'trades')    fetchTrades();
    if (name === 'orders')    fetchOrders();
    if (name === 'sectors')   loadHeatmap();
    if (name === 'trade')     initTradePage();
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('collapsed');
}

// ─── CORE REFRESH ────────────────────────────────────────────
async function refreshCore() {
    await Promise.allSettled([
        fetchStatus(),
        fetchPnL(),
        fetchWatchlist(),
    ]);
    setText('last-update', 'Updated: ' + new Date().toLocaleTimeString('en-IN',
        { timeZone:'Asia/Kolkata', hour12:false }));
}

// ─── STATUS ──────────────────────────────────────────────────
async function fetchStatus() {
    const d = await api('/api/status');
    if (!d) return;

    _botRunning = d.bot_running;

    // Sync time from backend (IST)
    if (d.time && window._syncClockFromBackend) {
        window._syncClockFromBackend(d.time);
    }

    // Market
    const dot = document.getElementById('mktDot');
    const st  = document.getElementById('mktStatus');
    if (d.market_status === 'OPEN') {
        dot.className = 'dot green';
        st.textContent = 'Market Open';
        st.className   = 'green';
    } else if (d.market_status === 'PRE_MARKET') {
        dot.className = 'dot yellow';
        st.textContent = 'Pre-Market';
        st.className   = 'yellow';
    } else {
        dot.className = 'dot red';
        st.textContent = 'Market Closed';
        st.className   = 'red';
    }

    // Bot
    const btnStart = document.getElementById('btnStart');
    const btnStop  = document.getElementById('btnStop');
    const botTxt   = document.getElementById('bot-status-txt');
    if (d.bot_running) {
        btnStart.style.display = 'none';
        btnStop.style.display  = '';
        botTxt.textContent = '● Bot Running';
        botTxt.className   = 'green';
    } else {
        btnStart.style.display = '';
        btnStop.style.display  = 'none';
        botTxt.textContent = '● Bot Stopped';
        botTxt.className   = 'red';
    }

    // Halt
    const haltEl = document.getElementById('halt-alert');
    if (haltEl) haltEl.style.display = (d.trading_halted) ? '' : 'none';

    // Sidebar user
    if (d.user_name) setText('sidebarUser', d.user_name);
    setText('sidebarMode', d.is_paper ? '📄 PAPER' : '🔴 LIVE');
}

// ─── P&L ─────────────────────────────────────────────────────
async function fetchPnL() {
    const d = await api('/api/pnl');
    if (!d) return;

    const pnl     = d.daily_pnl   || 0;
    const pct     = d.daily_pnl_pct || 0;
    const sign    = pnl >= 0 ? '+' : '';
    const cls     = pnl >= 0 ? 'green' : 'red';

    // Stat cards
    const pnlEl  = document.getElementById('d-pnl');
    const pctEl  = document.getElementById('d-pnl-pct');
    if (pnlEl) { pnlEl.textContent = `${sign}₹${Math.abs(pnl).toLocaleString('en-IN', {maximumFractionDigits:2})}`; pnlEl.className = `stat-value ${cls}`; }
    if (pctEl) { pctEl.textContent = `${sign}${pct.toFixed(2)}%`; pctEl.className = `stat-sub ${cls}`; }

    setText('d-capital', '₹' + fmtLarge(d.current_capital || 0));
    setText('d-trades',  d.total_trades || 0);

    const winEl  = document.getElementById('d-win');
    const lossEl = document.getElementById('d-loss');
    if (winEl)  { winEl.textContent  = (d.winners || 0) + 'W'; }
    if (lossEl) { lossEl.textContent = (d.losers  || 0) + 'L'; }

    const wr = d.win_rate || 0;
    const wrEl = document.getElementById('d-wr');
    if (wrEl) { wrEl.textContent = wr.toFixed(1) + '%'; wrEl.className = `stat-value ${wr >= 50 ? 'green' : wr > 0 ? 'yellow' : ''}`; }

    // Top bar P&L
    const topPnl = document.getElementById('topPnl');
    if (topPnl) { topPnl.textContent = `${sign}₹${Math.abs(pnl).toLocaleString('en-IN', {maximumFractionDigits:0})}`; topPnl.className = cls; }

    // Risk bar
    const lu = d.loss_used_pct || 0;
    const luEl  = document.getElementById('d-loss-pct');
    const barEl = document.getElementById('d-risk-bar');
    if (luEl) { luEl.textContent = lu.toFixed(1) + '%'; luEl.className = `stat-value ${lu >= 80 ? 'red' : lu >= 50 ? 'yellow' : 'green'}`; }
    if (barEl) { barEl.style.width = Math.min(lu, 100) + '%'; barEl.style.background = lu >= 80 ? 'var(--red)' : lu >= 50 ? 'var(--yellow)' : 'var(--green)'; }

    // Pos count badges
    const ap = d.active_positions || 0;
    setText('d-pos', ap);
    setText('pos-badge', ap);
    setText('d-pos-count', ap);
    setText('pos-total', ap);
}

// ─── POSITIONS ───────────────────────────────────────────────
async function fetchPositions() {
    const list = await api('/api/positions');
    if (!Array.isArray(list)) return;

    const rows = list.length === 0
        ? '<tr><td colspan="10" class="empty">No active positions</td></tr>'
        : list.map(p => {
            const pc = p.pnl >= 0 ? 'green' : 'red';
            const dc = p.direction === 'LONG' ? 'dir-long' : 'dir-short';
            const arrow = p.direction === 'LONG' ? '▲' : '▼';
            return `<tr>
                <td><b>${p.symbol}</b></td>
                <td class="dim">${p.strategy}</td>
                <td class="${dc}">${arrow} ${p.direction}</td>
                <td>${p.qty}</td>
                <td>₹${p.entry.toFixed(2)}</td>
                <td><b>₹${p.ltp.toFixed(2)}</b></td>
                <td class="${pc}"><b>${p.pnl >= 0 ? '+' : ''}₹${p.pnl.toFixed(0)}</b></td>
                <td class="${pc}">${p.pnl_pct >= 0 ? '+' : ''}${p.pnl_pct.toFixed(2)}%</td>
                <td class="red">₹${p.sl.toFixed(2)}</td>
                <td class="green">₹${p.target.toFixed(2)}</td>
            </tr>`;
        }).join('');

    setHTML('d-positions', rows);
    setHTML('pos-body', rows);
}

// ─── WATCHLIST ───────────────────────────────────────────────
async function fetchWatchlist() {
    const list = await api('/api/watchlist');
    if (!Array.isArray(list)) return;

    const rows = list.length === 0
        ? '<tr><td colspan="4" class="empty">No data</td></tr>'
        : list.map(item => {
            const chg = item.change_pct || 0;
            const cc  = chg >= 0 ? 'green' : 'red';
            const inP = item.in_position ? ' <span style="color:var(--green);font-size:9px">●</span>' : '';
            return `<tr>
                <td><b>${item.symbol}</b>${inP}</td>
                <td>${item.ltp > 0 ? '₹' + item.ltp.toFixed(2) : '--'}</td>
                <td class="${cc}">${item.ltp > 0 ? (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '--'}</td>
                <td class="dim" style="font-size:10px">${item.volume > 0 ? fmtVol(item.volume) : ''}</td>
            </tr>`;
        }).join('');

    setHTML('d-watchlist', rows);
}

// ─── TRADES ──────────────────────────────────────────────────
async function fetchTrades() {
    const list = await api('/api/trades');
    if (!Array.isArray(list)) return;

    setText('trades-total', list.length + ' trades');

    if (list.length === 0) {
        setHTML('trades-body', '<tr><td colspan="11" class="empty">No trades today</td></tr>');
        return;
    }

    setHTML('trades-body', [...list].reverse().map(t => {
        const pc = t.pnl >= 0 ? 'green' : 'red';
        const dc = t.direction === 'LONG' ? 'dir-long' : 'dir-short';
        const chip = t.pnl >= 0 ? '<span class="chip-win">WIN</span>' : '<span class="chip-loss">LOSS</span>';
        return `<tr>
            <td class="dim">${t.exit_time || '--'}</td>
            <td><b>${t.symbol}</b></td>
            <td class="dim">${t.strategy || '--'}</td>
            <td class="${dc}">${t.direction}</td>
            <td>${t.qty}</td>
            <td>₹${t.entry.toFixed(2)}</td>
            <td>₹${t.exit.toFixed(2)}</td>
            <td class="${pc}"><b>${t.pnl >= 0 ? '+' : ''}₹${t.pnl.toFixed(0)}</b></td>
            <td class="${pc}">${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(2)}%</td>
            <td>${chip}</td>
            <td class="dim" style="max-width:160px;overflow:hidden;text-overflow:ellipsis" title="${t.exit_reason || ''}">${(t.exit_reason || '--').substring(0,25)}</td>
        </tr>`;
    }).join(''));
}

// ─── ORDERS ──────────────────────────────────────────────────
async function fetchOrders() {
    const list = await api('/api/orders');
    if (!Array.isArray(list)) return;

    setText('orders-total', list.length);

    if (list.length === 0) {
        setHTML('orders-body', '<tr><td colspan="9" class="empty">No orders</td></tr>');
        return;
    }

    setHTML('orders-body', [...list].reverse().map(o => {
        const dc  = o.transaction === 'BUY' ? 'green' : 'red';
        const stc = { COMPLETE:'st-complete', OPEN:'st-open', CANCELLED:'st-cancelled', REJECTED:'st-rejected', PAPER:'st-paper' }[o.status] || '';
        return `<tr>
            <td class="dim" style="font-family:monospace;font-size:11px">${o.order_id}</td>
            <td><b>${o.symbol}</b></td>
            <td class="dim">${o.type}</td>
            <td class="${dc}"><b>${o.transaction}</b></td>
            <td>${o.qty}</td>
            <td>${o.price > 0 ? '₹' + o.price.toFixed(2) : 'MKT'}</td>
            <td class="dim">${o.product}</td>
            <td class="${stc}">${o.status}</td>
            <td class="dim" style="font-size:11px">${o.tag || '--'}</td>
        </tr>`;
    }).join(''));
}

// ─── BOT CONTROL ─────────────────────────────────────────────
async function botControl(action) {
    const res = await api(`/api/bot/${action}`, 'POST');
    if (res?.success) {
        showToast(res.message, 'toast-success');
        await fetchStatus();
    } else {
        showToast(res?.error || 'Error!', 'toast-error');
    }
}

// ─── HELPERS ─────────────────────────────────────────────────
async function api(url, method = 'GET', body = null) {
    try {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        if (!res.ok) return null;
        return await res.json();
    } catch (e) { return null; }
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

function setHTML(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

function fmtLarge(n) {
    if (n >= 10000000) return (n/10000000).toFixed(2) + 'Cr';
    if (n >= 100000)   return (n/100000).toFixed(2) + 'L';
    return n.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

function fmtVol(v) {
    if (v >= 1000000) return (v/1000000).toFixed(1) + 'M';
    if (v >= 1000)    return (v/1000).toFixed(0) + 'K';
    return v;
}

function showToast(msg, cls = 'toast-info') {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className   = `toast ${cls} show`;
    setTimeout(() => { t.className = 'toast'; }, 3000);
}
