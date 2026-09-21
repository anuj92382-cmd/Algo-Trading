
/**
 * paper.js - Paper Trading Portfolio Frontend Logic
 * Positions, Orders, Live P&L tracking
 */

let _paperPositions = [];
let _paperOrders    = [];
let _paperLiveTimer = null;

// ─── INIT ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Check if paper mode
    checkPaperMode();
});

async function checkPaperMode() {
    try {
        const st = await api('/api/status');
        if (st && st.is_paper) {
            // Show paper portfolio section
            const portfolioEl = document.getElementById('paper-portfolio');
            if (portfolioEl) portfolioEl.style.display = 'block';
            
            // Load initial data
            loadPaperPortfolio();
            
            // Start live P&L updates (every 30 seconds)
            startPaperLiveUpdates();
        }
    } catch (err) {
        console.warn('Paper mode check failed:', err);
    }
}

// ─── LOAD PORTFOLIO ──────────────────────────────────────────
async function loadPaperPortfolio() {
    await Promise.all([
        loadPaperPositions(),
        loadPaperOrders(),
    ]);
}

async function loadPaperPositions() {
    try {
        const data = await api('/api/trade/paper_positions');
        if (!data) return;

        _paperPositions = data.positions || [];

        // Update summary cards
        setText('paper-total-pnl',  formatCurrency(data.total_pnl || 0));
        setText('paper-total-pct',  (data.overall_pct || 0).toFixed(2) + '%');
        setText('paper-invested',   formatCurrency(data.total_invested || 0));
        setText('paper-closed-pnl', formatCurrency(data.closed_pnl || 0));
        setText('paper-pos-count',  data.count || 0);

        // Color code total P&L
        const pnlEl = document.getElementById('paper-total-pnl');
        if (pnlEl) {
            pnlEl.className = 'paper-sum-val ' + ((data.total_pnl || 0) >= 0 ? 'green' : 'red');
        }
        const pctEl = document.getElementById('paper-total-pct');
        if (pctEl) {
            pctEl.className = 'paper-sum-sub ' + ((data.overall_pct || 0) >= 0 ? 'green' : 'red');
        }
        const closedEl = document.getElementById('paper-closed-pnl');
        if (closedEl) {
            closedEl.className = 'paper-sum-val ' + ((data.closed_pnl || 0) >= 0 ? 'green' : 'red');
        }

        // Render positions table
        renderPaperPositions(_paperPositions);

    } catch (err) {
        console.error('Load paper positions error:', err);
        showToast('❌ Paper positions load failed', 'toast-error');
    }
}

async function loadPaperOrders() {
    try {
        const data = await api('/api/trade/paper_orders?limit=50');
        if (!data) return;

        _paperOrders = data.orders || [];
        renderPaperOrders(_paperOrders);

    } catch (err) {
        console.error('Load paper orders error:', err);
    }
}

// ─── RENDER POSITIONS ────────────────────────────────────────
function renderPaperPositions(positions) {
    const tbody = document.getElementById('paper-positions-body');
    if (!tbody) return;

    if (!positions || positions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" class="empty">
            Koi open position nahi hai. Scanner se trade karo!
        </td></tr>`;
        return;
    }

    tbody.innerHTML = positions.map(pos => {
        const isLong    = pos.quantity > 0;
        const pnlCls    = pos.pnl >= 0 ? 'green' : 'red';
        const pnlIcon   = pos.pnl >= 0 ? '📈' : '📉';
        const qtyIcon   = isLong ? '🟢' : '🔴';
        const slDisplay = pos.stop_loss > 0 ? `₹${pos.stop_loss.toFixed(2)}` : '--';
        const tgDisplay = pos.target > 0 ? `₹${pos.target.toFixed(2)}` : '--';

        return `
<tr data-symbol="${pos.symbol}">
    <td><b>${pos.symbol}</b></td>
    <td>${qtyIcon} ${Math.abs(pos.quantity)}</td>
    <td>₹${pos.avg_price.toFixed(2)}</td>
    <td class="paper-ltp" data-sym="${pos.symbol}">₹${pos.ltp.toFixed(2)}</td>
    <td class="${pnlCls}"><b>${pnlIcon} ₹${pos.pnl.toFixed(2)}</b></td>
    <td class="${pnlCls}">${pos.pnl_pct.toFixed(2)}%</td>
    <td><span class="badge grey">${pos.product}</span></td>
    <td class="dim" style="font-size:11px">${pos.entry_time.split(' ')[1]}</td>
    <td class="dim">${slDisplay}</td>
    <td class="dim">${tgDisplay}</td>
    <td>
        <button class="btn btn-red btn-sm"
                onclick="exitPaperPosition('${pos.symbol}', ${pos.ltp})">
            ⚡ Exit
        </button>
    </td>
</tr>`;
    }).join('');
}

// ─── RENDER ORDERS ───────────────────────────────────────────
function renderPaperOrders(orders) {
    const tbody = document.getElementById('paper-orders-body');
    if (!tbody) return;

    if (!orders || orders.length === 0) {
        tbody.innerHTML = `<tr><td colspan="10" class="empty">
            Koi order nahi hai abhi tak
        </td></tr>`;
        return;
    }

    tbody.innerHTML = orders.map(ord => {
        const txnCls   = ord.transaction === 'BUY' ? 'green' : 'red';
        const txnIcon  = ord.transaction === 'BUY' ? '📈' : '📉';
        const shortId  = ord.order_id.substring(0, 12) + '...';

        return `
<tr>
    <td class="dim" style="font-size:10px" title="${ord.order_id}">${shortId}</td>
    <td><b>${ord.symbol}</b></td>
    <td class="${txnCls}">${txnIcon} ${ord.transaction}</td>
    <td>${ord.quantity}</td>
    <td>₹${ord.price.toFixed(2)}</td>
    <td><span class="badge grey">${ord.order_type}</span></td>
    <td><span class="badge blue">${ord.product}</span></td>
    <td class="dim">${ord.tag}</td>
    <td class="dim" style="font-size:11px">${ord.timestamp.split(' ')[1]}</td>
    <td><span class="badge green">${ord.status}</span></td>
</tr>`;
    }).join('');
}

// ─── TAB SWITCH ──────────────────────────────────────────────
function switchPaperTab(tab) {
    // Update tab buttons
    document.querySelectorAll('.paper-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // Show/hide content
    document.getElementById('paper-positions-tab').style.display = tab === 'positions' ? 'block' : 'none';
    document.getElementById('paper-orders-tab').style.display    = tab === 'orders'    ? 'block' : 'none';
}

// ─── EXIT POSITION ───────────────────────────────────────────
async function exitPaperPosition(symbol, currentPrice) {
    if (!confirm(`Exit paper position ${symbol} @ ₹${currentPrice.toFixed(2)}?`)) {
        return;
    }

    try {
        const res = await api('/api/trade/paper_exit', 'POST', {
            symbol: symbol,
            price:  currentPrice,
        });

        if (res && res.success) {
            showToast(`✅ ${symbol} position closed!`, 'toast-success');
            loadPaperPortfolio();
        } else {
            showToast(`❌ ${res?.error || 'Exit failed'}`, 'toast-error');
        }
    } catch (err) {
        showToast('❌ Exit error: ' + err.message, 'toast-error');
    }
}

// ─── RESET PORTFOLIO ─────────────────────────────────────────
async function resetPaperPortfolio() {
    if (!confirm('🗑️ Reset paper portfolio?\n\nSaare positions aur orders delete ho jayenge. Yeh action undo nahi ho sakta!')) {
        return;
    }

    try {
        const res = await api('/api/trade/paper_reset', 'POST', {});
        
        if (res && res.success) {
            showToast('✅ Paper portfolio reset ho gaya', 'toast-success');
            _paperPositions = [];
            _paperOrders    = [];
            loadPaperPortfolio();
        } else {
            showToast(`❌ ${res?.error || 'Reset failed'}`, 'toast-error');
        }
    } catch (err) {
        showToast('❌ Reset error: ' + err.message, 'toast-error');
    }
}

// ─── LIVE P&L UPDATES ────────────────────────────────────────
function startPaperLiveUpdates() {
    // Stop existing timer
    if (_paperLiveTimer) clearInterval(_paperLiveTimer);

    // Update every 30 seconds
    _paperLiveTimer = setInterval(updatePaperLivePrices, 30000);
}

async function updatePaperLivePrices() {
    if (_paperPositions.length === 0) return;

    try {
        // Fetch latest positions (with fresh LTP)
        const data = await api('/api/trade/paper_positions');
        if (!data || !data.positions) return;

        _paperPositions = data.positions;

        // Update summary
        setText('paper-total-pnl',  formatCurrency(data.total_pnl || 0));
        setText('paper-total-pct',  (data.overall_pct || 0).toFixed(2) + '%');
        
        const pnlEl = document.getElementById('paper-total-pnl');
        if (pnlEl) {
            pnlEl.className = 'paper-sum-val ' + ((data.total_pnl || 0) >= 0 ? 'green' : 'red');
        }

        // Update LTP + P&L in table without full re-render
        data.positions.forEach(pos => {
            const row = document.querySelector(`#paper-positions-body tr[data-symbol="${pos.symbol}"]`);
            if (!row) return;

            const ltpCell = row.querySelector('.paper-ltp');
            const pnlCell = row.cells[4];  // P&L ₹ column
            const pctCell = row.cells[5];  // P&L % column

            if (ltpCell) ltpCell.textContent = `₹${pos.ltp.toFixed(2)}`;
            
            if (pnlCell) {
                const pnlCls  = pos.pnl >= 0 ? 'green' : 'red';
                const pnlIcon = pos.pnl >= 0 ? '📈' : '📉';
                pnlCell.className = pnlCls;
                pnlCell.innerHTML = `<b>${pnlIcon} ₹${pos.pnl.toFixed(2)}</b>`;
            }

            if (pctCell) {
                const pctCls = pos.pnl_pct >= 0 ? 'green' : 'red';
                pctCell.className = pctCls;
                pctCell.textContent = pos.pnl_pct.toFixed(2) + '%';
            }
        });

    } catch (err) {
        console.warn('Live P&L update failed:', err);
    }
}

// ─── UTILS ───────────────────────────────────────────────────
function formatCurrency(val) {
    if (val === 0) return '₹0';
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : '';
    return sign + '₹' + abs.toLocaleString('en-IN', {maximumFractionDigits: 2});
}
