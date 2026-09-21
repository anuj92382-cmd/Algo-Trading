/**
 * trade.js - Buy/Sell Trading Logic
 * Zerodha Kite API se direct order placement
 */

// ── State ────────────────────────────────────────────────────
let _tradeDir     = 'BUY';       // BUY or SELL
let _orderType    = 'MARKET';    // MARKET/LIMIT/SL/SL-M
let _currentQuote = null;        // Latest fetched quote
let _pendingOrder = null;        // Order waiting for confirmation
let _quoteTimer   = null;        // Auto-refresh quote timer

// ─────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────
function initTradePage() {
    loadFunds();
    loadTradePositions();
    loadHoldings();
    loadTradeOrders();

    // Paper mode check
    api('/api/status').then(st => {
        const warn = document.getElementById('tr-paper-warn');
        if (warn) warn.style.display = st?.is_paper ? 'flex' : 'none';
    });
}

// ─────────────────────────────────────────────────────────────
// TAB: BUY / SELL
// ─────────────────────────────────────────────────────────────
function setTradeTab(dir) {
    _tradeDir = dir;

    // Tab styling
    const buyTab  = document.getElementById('tab-buy');
    const sellTab = document.getElementById('tab-sell');
    const btn     = document.getElementById('tr-submit-btn');

    if (dir === 'BUY') {
        buyTab?.classList.add('active');
        sellTab?.classList.remove('active');
        if (btn) { btn.textContent = '📈 BUY'; btn.className = 'tr-submit-btn buy'; }
    } else {
        sellTab?.classList.add('active');
        buyTab?.classList.remove('active');
        if (btn) { btn.textContent = '📉 SELL'; btn.className = 'tr-submit-btn sell'; }
    }

    calcRR();
}

// ─────────────────────────────────────────────────────────────
// ORDER TYPE
// ─────────────────────────────────────────────────────────────
function setOrderType(ot) {
    _orderType = ot;

    // Button styles
    document.querySelectorAll('.tr-ot-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.ot === ot);
    });

    // Show/hide fields
    const priceField   = document.getElementById('tr-price-field');
    const trigField    = document.getElementById('tr-trigger-field');
    const priceInput   = document.getElementById('tr-price');
    const priceLbl     = document.getElementById('tr-price-lbl');

    const needPrice    = ot === 'LIMIT' || ot === 'SL';
    const needTrigger  = ot === 'SL' || ot === 'SL-M';

    if (priceInput) {
        priceInput.disabled = !needPrice;
        priceInput.value    = needPrice ? (priceInput.value || '') : '';
    }
    if (priceLbl)  priceLbl.textContent  = needPrice ? '' : '(Market)';
    if (trigField) trigField.style.display = needTrigger ? 'block' : 'none';

    // Pre-fill price with LTP for LIMIT orders
    if (needPrice && _currentQuote?.ltp > 0 && !document.getElementById('tr-price').value) {
        document.getElementById('tr-price').value = _currentQuote.ltp.toFixed(2);
    }

    calcOrderValue();
}

// ─────────────────────────────────────────────────────────────
// PRODUCT CHANGE
// ─────────────────────────────────────────────────────────────
function onProductChange() {
    const prod = document.getElementById('tr-product')?.value || 'MIS';
    const btn  = document.getElementById('tr-submit-btn');
    if (btn) btn.textContent = `${_tradeDir === 'BUY' ? '📈 BUY' : '📉 SELL'} (${prod})`;
}

// ─────────────────────────────────────────────────────────────
// SYMBOL INPUT
// ─────────────────────────────────────────────────────────────
function onSymbolInput() {
    // Hide old quote
    const box = document.getElementById('tr-quote-box');
    if (box) box.style.display = 'none';
    _currentQuote = null;
    // Stop auto-refresh
    if (_quoteTimer) { clearInterval(_quoteTimer); _quoteTimer = null; }
}

// ─────────────────────────────────────────────────────────────
// FETCH LIVE QUOTE
// ─────────────────────────────────────────────────────────────
async function fetchQuote() {
    const sym  = (document.getElementById('tr-symbol')?.value || '').trim().toUpperCase();
    const exch = document.getElementById('tr-exchange')?.value || 'NSE';
    if (!sym) { showToast('Symbol daalo!', 'toast-error'); return; }

    const data = await api(`/api/trade/quote?symbol=${sym}&exchange=${exch}`);
    if (!data || data.error) {
        showToast(data?.error || `${sym} ka quote nahi mila`, 'toast-error');
        return;
    }

    _currentQuote = data;
    _showQuote(data);

    // Auto-refresh every 5s
    if (_quoteTimer) clearInterval(_quoteTimer);
    _quoteTimer = setInterval(async () => {
        const fresh = await api(`/api/trade/quote?symbol=${sym}&exchange=${exch}`);
        if (fresh && !fresh.error) { _currentQuote = fresh; _showQuote(fresh); calcRR(); }
    }, 5000);

    // Pre-fill price for LIMIT orders
    if (_orderType === 'LIMIT') {
        const priceEl = document.getElementById('tr-price');
        if (priceEl && !priceEl.value) priceEl.value = data.ltp.toFixed(2);
    }

    calcOrderValue();
    calcRR();
}

function _showQuote(data) {
    const box = document.getElementById('tr-quote-box');
    if (!box) return;
    box.style.display = 'flex';

    setText('tr-q-sym', data.symbol);
    setText('tr-q-ltp', `₹${data.ltp?.toFixed(2) || '0'}`);

    const chg    = data.change_pct || 0;
    const sign   = chg >= 0 ? '+' : '';
    const chgEl  = document.getElementById('tr-q-chg');
    if (chgEl) {
        chgEl.textContent = `${sign}${chg.toFixed(2)}%`;
        chgEl.className   = chg >= 0 ? 'green' : 'red';
    }
    setText('tr-q-ohlc',
        `O:₹${data.open?.toFixed(0)} H:₹${data.high?.toFixed(0)} L:₹${data.low?.toFixed(0)}`);
}

// ─────────────────────────────────────────────────────────────
// CALCULATIONS
// ─────────────────────────────────────────────────────────────
function calcOrderValue() {
    const qty      = parseInt(document.getElementById('tr-qty')?.value   || 0);
    const priceInp = document.getElementById('tr-price');
    let price      = parseFloat(priceInp?.value || 0);

    // Use LTP for MARKET orders
    if (_orderType === 'MARKET' && _currentQuote?.ltp > 0) price = _currentQuote.ltp;

    const val   = qty * price;
    const valEl = document.getElementById('tr-order-val');
    if (valEl) {
        valEl.textContent = val > 0 ? `₹${val.toLocaleString('en-IN', {maximumFractionDigits:2})}` : '₹0';
    }
}

function calcRR() {
    const qty     = parseInt(document.getElementById('tr-qty')?.value || 0);
    const slVal   = parseFloat(document.getElementById('tr-sl')?.value     || 0);
    const tgtVal  = parseFloat(document.getElementById('tr-target')?.value || 0);
    const rrEl    = document.getElementById('tr-rr-display');
    const rrTxt   = document.getElementById('tr-rr-text');
    const riskTxt = document.getElementById('tr-risk-text');
    const rewTxt  = document.getElementById('tr-reward-text');

    const ltp = _currentQuote?.ltp || parseFloat(document.getElementById('tr-price')?.value || 0);

    if (!rrEl) return;

    if (slVal > 0 && tgtVal > 0 && ltp > 0) {
        const risk   = Math.abs(ltp - slVal);
        const reward = Math.abs(tgtVal - ltp);
        const rr     = reward / (risk || 1);
        const rrCol  = rr >= 2 ? 'var(--green)' : rr >= 1.5 ? 'var(--blue)' : 'var(--yellow)';

        rrEl.style.display = 'flex';
        if (rrTxt) {
            rrTxt.textContent = `R:R = 1:${rr.toFixed(1)}`;
            rrTxt.style.color = rrCol;
        }
        if (riskTxt)  riskTxt.textContent  = `Risk: ₹${(risk*qty).toFixed(0)}`;
        if (rewTxt)   rewTxt.textContent   = `Reward: ₹${(reward*qty).toFixed(0)}`;
    } else {
        rrEl.style.display = 'none';
    }
}

// ─────────────────────────────────────────────────────────────
// SUBMIT ORDER (shows confirmation modal)
// ─────────────────────────────────────────────────────────────
function submitOrder() {
    const sym   = (document.getElementById('tr-symbol')?.value   || '').trim().toUpperCase();
    const exch  = document.getElementById('tr-exchange')?.value  || 'NSE';
    const prod  = document.getElementById('tr-product')?.value   || 'MIS';
    const qty   = parseInt(document.getElementById('tr-qty')?.value   || 0);
    const price = parseFloat(document.getElementById('tr-price')?.value || 0);
    const trig  = parseFloat(document.getElementById('tr-trigger')?.value || 0);
    const sl    = parseFloat(document.getElementById('tr-sl')?.value     || 0);
    const tgt   = parseFloat(document.getElementById('tr-target')?.value || 0);

    // Validation
    if (!sym)     { showToast('Symbol daalo!', 'toast-error'); return; }
    if (qty <= 0) { showToast('Quantity 1 ya zyada honi chahiye!', 'toast-error'); return; }
    if (_orderType === 'LIMIT' && price <= 0) {
        showToast('LIMIT order ke liye price daalo!', 'toast-error'); return;
    }
    if ((_orderType === 'SL' || _orderType === 'SL-M') && trig <= 0) {
        showToast('SL order ke liye trigger price daalo!', 'toast-error'); return;
    }

    const ltp = _currentQuote?.ltp || price || 0;
    const estVal = qty * (price > 0 ? price : ltp);

    _pendingOrder = { sym, exch, prod, qty, price, trig, sl, tgt };

    // Build confirmation modal content
    const dirCls    = _tradeDir === 'BUY' ? 'buy' : 'sell';
    const dirIcon   = _tradeDir === 'BUY' ? '📈' : '📉';
    const isPaper   = document.getElementById('tr-paper-warn')?.style.display !== 'none';

    const slRow     = sl  > 0 ? `<div class="tr-conf-row"><span>Stop Loss</span><span class="red">₹${sl.toFixed(2)}</span></div>` : '';
    const tgtRow    = tgt > 0 ? `<div class="tr-conf-row"><span>Target</span><span class="green">₹${tgt.toFixed(2)}</span></div>` : '';
    const rrRow     = sl > 0 && tgt > 0 && ltp > 0 ? (() => {
        const rr = Math.abs(tgt-ltp) / Math.abs(ltp-sl);
        return `<div class="tr-conf-row"><span>R:R Ratio</span><span style="color:${rr>=2?'var(--green)':'var(--yellow)'}">1:${rr.toFixed(1)}</span></div>`;
    })() : '';

    document.getElementById('tr-modal-title').textContent =
        `${dirIcon} Confirm ${_tradeDir} Order`;

    document.getElementById('tr-modal-body').innerHTML = `
        ${isPaper ? '<div class="tr-modal-paper">📄 PAPER MODE - No real order</div>' : ''}
        <div class="tr-conf-grid">
            <div class="tr-conf-row highlight ${dirCls}">
                <span>Action</span>
                <span><b>${_tradeDir} ${sym}</b></span>
            </div>
            <div class="tr-conf-row"><span>Exchange</span><span>${exch}</span></div>
            <div class="tr-conf-row"><span>Product</span><span>${prod}</span></div>
            <div class="tr-conf-row"><span>Order Type</span><span>${_orderType}</span></div>
            <div class="tr-conf-row"><span>Quantity</span><span><b>${qty} shares</b></span></div>
            <div class="tr-conf-row"><span>Price</span>
                <span>${_orderType === 'MARKET' ? `MARKET (LTP ≈ ₹${ltp.toFixed(2)})` : `₹${price.toFixed(2)}`}</span>
            </div>
            ${trig > 0 ? `<div class="tr-conf-row"><span>Trigger Price</span><span>₹${trig.toFixed(2)}</span></div>` : ''}
            ${slRow}${tgtRow}${rrRow}
            <div class="tr-conf-row total">
                <span>Est. Value</span>
                <span><b>₹${estVal.toLocaleString('en-IN',{maximumFractionDigits:2})}</b></span>
            </div>
        </div>`;

    // Confirm button color
    const confBtn = document.getElementById('tr-confirm-btn');
    if (confBtn) {
        confBtn.className = `tr-confirm-btn ${dirCls}`;
        confBtn.textContent = isPaper
            ? `📄 Place PAPER ${_tradeDir} Order`
            : `✅ Place ${_tradeDir} Order`;
    }

    document.getElementById('tr-confirm-modal').style.display = 'flex';
}

// ─────────────────────────────────────────────────────────────
// CONFIRM & PLACE ORDER
// ─────────────────────────────────────────────────────────────
async function confirmOrder() {
    if (!_pendingOrder) return;

    const confBtn = document.getElementById('tr-confirm-btn');
    if (confBtn) { confBtn.disabled = true; confBtn.textContent = '⏳ Placing...'; }

    const { sym, exch, prod, qty, price, trig, sl, tgt } = _pendingOrder;

    const payload = {
        symbol:        sym,
        exchange:      exch,
        transaction:   _tradeDir,
        quantity:      qty,
        order_type:    _orderType,
        product:       prod,
        price:         price,
        trigger_price: trig,
        stop_loss:     sl,
        target:        tgt,
        tag:           'MANUAL',
    };

    const res = await api('/api/trade/place', 'POST', payload);

    closeTradeModal();
    if (confBtn) { confBtn.disabled = false; }

    if (res?.success) {
        const isPaper = res.paper_mode;
        showToast(
            isPaper
                ? `📄 PAPER: ${_tradeDir} ${qty} ${sym} order recorded`
                : `✅ ${_tradeDir} ${qty} ${sym} order placed! ID: ${res.order_id?.substring(0,10)}`,
            'toast-success'
        );
        // Refresh data
        setTimeout(() => {
            loadFunds();
            loadTradePositions();
            loadTradeOrders();
        }, 1500);
    } else {
        showToast(`❌ Order failed: ${res?.error || 'Unknown error'}`, 'toast-error');
    }

    _pendingOrder = null;
}

function closeTradeModal() {
    document.getElementById('tr-confirm-modal').style.display = 'none';
    _pendingOrder = null;
}

// ─────────────────────────────────────────────────────────────
// EXIT POSITION
// ─────────────────────────────────────────────────────────────
async function exitPosition(symbol, qty, product, exchange, direction) {
    if (!confirm(`${symbol} - ${qty} qty exit karna chahte ho?`)) return;

    // direction: 'long' → SELL to exit, 'short' → BUY to exit
    const txn = direction === 'long' ? 'SELL' : 'BUY';

    const res = await api('/api/trade/exit', 'POST', {
        symbol, exchange: exchange || 'NSE',
        product: product || 'MIS',
        quantity: qty, transaction: txn,
    });

    if (res?.success) {
        showToast(`✅ Exit order placed for ${qty} ${symbol}`, 'toast-success');
        setTimeout(() => { loadTradePositions(); loadFunds(); }, 1500);
    } else {
        showToast(`❌ Exit failed: ${res?.error}`, 'toast-error');
    }
}

async function exitHolding(symbol, qty) {
    if (!confirm(`${symbol} - ${qty} shares sell karna chahte ho? (CNC)`)) return;

    const res = await api('/api/trade/exit', 'POST', {
        symbol, exchange: 'NSE', product: 'CNC',
        quantity: qty, transaction: 'SELL',
    });

    if (res?.success) {
        showToast(`✅ ${symbol} sell order placed`, 'toast-success');
        setTimeout(() => { loadHoldings(); loadFunds(); }, 2000);
    } else {
        showToast(`❌ Sell failed: ${res?.error}`, 'toast-error');
    }
}

// ─────────────────────────────────────────────────────────────
// SQUARE OFF ALL
// ─────────────────────────────────────────────────────────────
async function confirmSquareoffAll() {
    if (!confirm('⚠️ Saari intraday (MIS) positions square off karna chahte ho?\n\nYeh action reversible nahi hai!')) return;
    const res = await api('/api/trade/squareoff_all', 'POST');
    if (res?.success) {
        showToast(res.message || '✅ Square off done!', 'toast-success');
        setTimeout(() => { loadTradePositions(); loadFunds(); }, 2000);
    } else {
        showToast(`❌ ${res?.error || 'Square off failed'}`, 'toast-error');
    }
}

// ─────────────────────────────────────────────────────────────
// LOAD DATA
// ─────────────────────────────────────────────────────────────
async function loadFunds() {
    const data = await api('/api/trade/funds');
    if (!data) return;

    const fmt = v => v > 0 ? `₹${parseFloat(v).toLocaleString('en-IN',{maximumFractionDigits:0})}` : '₹0';
    setText('tr-available', fmt(data.available));
    setText('tr-used',      fmt(data.used));
    setText('tr-net',       fmt(data.net));
}

async function loadTradePositions() {
    const data = await api('/api/trade/positions');
    const body = document.getElementById('tr-positions-body');
    if (!body) return;

    const pos = (data?.net || []).filter(p => p.quantity !== 0);
    setText('tr-pos-count', pos.length);

    if (!pos.length) {
        body.innerHTML = '<tr><td colspan="7" class="empty">No open positions</td></tr>';
        return;
    }

    body.innerHTML = pos.map(p => {
        const qty   = p.quantity || 0;
        const avg   = p.average_price || 0;
        const ltp   = p.last_price || avg;
        const pnl   = (ltp - avg) * Math.abs(qty);
        const pc    = pnl >= 0 ? 'green' : 'red';
        const sign  = pnl >= 0 ? '+' : '';
        const dir   = qty > 0 ? 'long' : 'short';
        const prod  = p.product || 'MIS';
        const exch  = p.exchange || 'NSE';
        const sym   = p.tradingsymbol || '';

        return `<tr>
            <td><b>${sym}</b></td>
            <td class="${qty>0?'green':'red'}">${qty}</td>
            <td class="dim">₹${avg.toFixed(2)}</td>
            <td><b>₹${ltp.toFixed(2)}</b></td>
            <td class="${pc}"><b>${sign}₹${Math.abs(pnl).toFixed(0)}</b></td>
            <td class="dim">${prod}</td>
            <td>
                <button class="btn-sm btn-red"
                        onclick="exitPosition('${sym}',${Math.abs(qty)},'${prod}','${exch}','${dir}')">
                    Exit
                </button>
            </td>
        </tr>`;
    }).join('');

    // Update dashboard P&L
    const totalPnl = pos.reduce((s, p) => {
        const avg = p.average_price || 0;
        const ltp = p.last_price || avg;
        return s + (ltp - avg) * Math.abs(p.quantity || 0);
    }, 0);
    const pnlEl  = document.getElementById('tr-pnl');
    if (pnlEl) {
        pnlEl.textContent = `${totalPnl>=0?'+':''}₹${Math.abs(totalPnl).toFixed(0)}`;
        pnlEl.className   = totalPnl >= 0 ? 'fund-val green' : 'fund-val red';
    }
}

async function loadHoldings() {
    const data = await api('/api/trade/holdings');
    const body = document.getElementById('tr-holdings-body');
    if (!body) return;

    const holdings = data?.holdings || [];
    setText('tr-hold-count', holdings.length);

    if (!holdings.length) {
        body.innerHTML = '<tr><td colspan="7" class="empty">No holdings</td></tr>';
        return;
    }

    body.innerHTML = holdings.map(h => {
        const qty    = h.quantity || 0;
        const avg    = h.average_price || 0;
        const ltp    = h.last_price || avg;
        const pnl    = (ltp - avg) * qty;
        const pnlPct = avg > 0 ? (ltp - avg) / avg * 100 : 0;
        const pc     = pnl >= 0 ? 'green' : 'red';
        const sign   = pnl >= 0 ? '+' : '';
        const sym    = h.tradingsymbol || '';

        return `<tr>
            <td><b>${sym}</b></td>
            <td>${qty}</td>
            <td class="dim">₹${avg.toFixed(2)}</td>
            <td><b>₹${ltp.toFixed(2)}</b></td>
            <td class="${pc}"><b>${sign}₹${Math.abs(pnl).toFixed(0)}</b></td>
            <td class="${pc}">${sign}${pnlPct.toFixed(2)}%</td>
            <td>
                <button class="btn-sm btn-red"
                        onclick="exitHolding('${sym}',${qty})">Sell</button>
            </td>
        </tr>`;
    }).join('');
}

async function loadTradeOrders() {
    const data = await api('/api/orders');
    const body = document.getElementById('tr-orders-body');
    if (!body) return;

    const orders = Array.isArray(data) ? data : [];
    setText('tr-ord-count', orders.length);

    if (!orders.length) {
        body.innerHTML = '<tr><td colspan="6" class="empty">No orders today</td></tr>';
        return;
    }

    body.innerHTML = [...orders].reverse().slice(0, 20).map(o => {
        const dc  = o.transaction === 'BUY' ? 'green' : 'red';
        const stc = {
            COMPLETE: 'st-complete', OPEN: 'st-open',
            CANCELLED: 'st-cancelled', REJECTED: 'st-rejected',
            PAPER: 'st-paper',
        }[o.status] || '';
        const price = o.price > 0 ? `₹${o.price.toFixed(2)}` : 'MKT';

        return `<tr>
            <td><b>${o.symbol}</b></td>
            <td class="${dc}"><b>${o.transaction}</b>
                <span class="dim" style="font-size:10px"> ${o.type}</span></td>
            <td>${o.qty}</td>
            <td class="dim">${price}</td>
            <td class="${stc}">${o.status}</td>
            <td class="dim" style="font-size:11px">${o.tag||'--'}</td>
        </tr>`;
    }).join('');
}

// ─────────────────────────────────────────────────────────────
// QUICK TRADE from Scanner / Heatmap
// Fill trade form with pre-loaded values
// ─────────────────────────────────────────────────────────────
function openTradeForm(symbol, direction, entry, sl, target, product) {
    showPage('trade');

    setTimeout(() => {
        const symEl = document.getElementById('tr-symbol');
        if (symEl) symEl.value = symbol;

        setTradeTab(direction);

        if (sl     > 0) document.getElementById('tr-sl').value     = sl.toFixed(2);
        if (target > 0) document.getElementById('tr-target').value = target.toFixed(2);
        if (product)    document.getElementById('tr-product').value = product;

        // Fetch fresh quote
        fetchQuote().then(() => {
            if (entry > 0 && _orderType === 'LIMIT') {
                document.getElementById('tr-price').value = entry.toFixed(2);
            }
            calcOrderValue();
            calcRR();
        });
    }, 100);
}

// Close modal on backdrop click
document.addEventListener('click', e => {
    const m = document.getElementById('tr-confirm-modal');
    if (m && e.target === m) closeTradeModal();
});
