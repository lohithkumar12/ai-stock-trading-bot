/* ==========================================================================
   AI Quant Trading Dashboard — Frontend Logic (US + India Markets)
   ========================================================================== */

let currentTab = 'us'; // 'us' | 'india'
let liveGeneration = 0;
let scannerGeneration = 0;
let liveAbort = null;
let scannerAbort = null;

document.addEventListener("DOMContentLoaded", () => {
    fetchLiveData();
    fetchScannerData();
    fetchLogs();
    fetchTrades();
    fetchHealth();
    setInterval(fetchLiveData, 3000);
    setInterval(fetchScannerData, 60000);
    setInterval(fetchLogs, 5000);
    setInterval(fetchTrades, 15000);
    setInterval(fetchHealth, 10000);
});

function isLiveStale(gen) {
    return gen !== liveGeneration;
}

function isScannerStale(gen) {
    return gen !== scannerGeneration;
}

function beginLiveFetch() {
    if (liveAbort) liveAbort.abort();
    liveAbort = new AbortController();
    liveGeneration += 1;
    return { gen: liveGeneration, signal: liveAbort.signal };
}

function beginScannerFetch() {
    if (scannerAbort) scannerAbort.abort();
    scannerAbort = new AbortController();
    scannerGeneration += 1;
    return { gen: scannerGeneration, signal: scannerAbort.signal };
}

function switchMarketTab(tab) {
    if (tab === currentTab) return;
    currentTab = tab;

    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.add('active');

    const universeSub = document.getElementById("kpi-universe-sub");
    const scannerTitle = document.getElementById("scanner-title");
    const positionsTitle = document.getElementById("positions-title");

    if (tab === 'us') {
        universeSub.textContent = "Universe: US Large-Caps (Alpaca)";
        scannerTitle.innerHTML = '<i class="fa-solid fa-radar"></i> US Strategy Scanner';
        positionsTitle.innerHTML = '<i class="fa-solid fa-list-check"></i> US Open Positions';
    } else {
        universeSub.textContent = "Universe: Nifty Large-Caps (Dhan / NSE)";
        scannerTitle.innerHTML = '<i class="fa-solid fa-radar"></i> India Strategy Scanner (NSE)';
        positionsTitle.innerHTML = '<i class="fa-solid fa-list-check"></i> India Open Positions';
    }

    clearMarketPanels(tab);
    fetchLiveData();
    fetchScannerData();
    fetchTrades();
}

function clearMarketPanels(tab) {
    document.getElementById("equity-val").textContent = "—";
    document.getElementById("equity-sub").textContent = "Loading…";
    document.getElementById("daily-pl-val").textContent = "—";
    document.getElementById("daily-pl-pct").textContent = "…";
    document.getElementById("daily-pl-val").style.color = "";
    document.getElementById("daily-pl-pct").className = "kpi-badge";
    document.getElementById("buying-power-val").textContent = "—";
    document.getElementById("cash-val").textContent = "…";
    document.getElementById("positions-count").textContent = "…";
    document.getElementById("table-count-tag").textContent = "Loading…";
    document.getElementById("market-status").textContent = "Loading…";
    document.getElementById("last-updated").textContent = "Updating…";

    document.getElementById("positions-tbody").innerHTML =
        `<tr><td colspan="9" class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i> Loading ${tab.toUpperCase()} positions…</td></tr>`;
    document.getElementById("scanner-container").innerHTML =
        `<div class="loading-state"><i class="fa-solid fa-spinner fa-spin"></i> Loading ${tab.toUpperCase()} scanner…</div>`;
}

function fetchLiveData() {
    const { gen, signal } = beginLiveFetch();
    if (currentTab === 'us') {
        fetchUSLive(gen, signal);
    } else {
        fetchIndiaLive(gen, signal);
    }
}

function fetchScannerData() {
    const { gen, signal } = beginScannerFetch();
    if (currentTab === 'us') {
        fetchUSScanner(gen, signal);
    } else {
        fetchIndiaScanner(gen, signal);
    }
}

function fetchCurrentTabData() {
    fetchLiveData();
    fetchScannerData();
}

async function fetchUSLive(gen, signal) {
    try {
        const [statusRes, positionsRes] = await Promise.all([
            fetch('/api/status', { signal }),
            fetch('/api/positions', { signal })
        ]);
        if (isLiveStale(gen)) return;

        if (statusRes.ok) {
            const status = await statusRes.json();
            if (isLiveStale(gen)) return;
            updateStatusUI(status, formatUSD);
        }

        if (positionsRes.ok) {
            const positions = await positionsRes.json();
            if (isLiveStale(gen)) return;
            updatePositionsUI(positions, formatUSD, 'closePosition');
        }
    } catch (err) {
        if (err.name === 'AbortError' || isLiveStale(gen)) return;
        console.error("Error fetching US live data:", err);
    }
}

async function fetchUSScanner(gen, signal) {
    try {
        const scannerRes = await fetch('/api/scanner', { signal });
        if (isScannerStale(gen) || !scannerRes.ok) return;
        const scanner = await scannerRes.json();
        if (isScannerStale(gen)) return;
        updateScannerUI(scanner, formatUSD);
    } catch (err) {
        if (err.name === 'AbortError' || isScannerStale(gen)) return;
        console.error("Error fetching US scanner:", err);
    }
}

async function fetchIndiaLive(gen, signal) {
    try {
        const [statusRes, positionsRes] = await Promise.all([
            fetch('/api/india/status', { signal }),
            fetch('/api/india/positions', { signal })
        ]);
        if (isLiveStale(gen)) return;

        if (statusRes.ok) {
            const status = await statusRes.json();
            if (isLiveStale(gen)) return;
            if (status.status === "disabled" || status.status === "error") {
                renderIndiaDisabledState(status.message);
                return;
            }
            updateIndiaStatusUI(status);
        } else {
            renderIndiaDisabledState("Add Dhan keys in environment");
        }

        if (positionsRes.ok) {
            const positions = await positionsRes.json();
            if (isLiveStale(gen)) return;
            updatePositionsUI(positions, formatINR, 'closeIndiaPosition');
        }
    } catch (err) {
        if (err.name === 'AbortError' || isLiveStale(gen)) return;
        console.error("Error fetching India live data:", err);
        renderIndiaDisabledState("Add Dhan keys in environment");
    }
}

async function fetchIndiaScanner(gen, signal) {
    try {
        const scannerRes = await fetch('/api/india/scanner', { signal });
        if (isScannerStale(gen) || !scannerRes.ok) return;
        const scanner = await scannerRes.json();
        if (isScannerStale(gen)) return;
        updateScannerUI(scanner, formatINR);
    } catch (err) {
        if (err.name === 'AbortError' || isScannerStale(gen)) return;
        console.error("Error fetching India scanner:", err);
    }
}

function updateKillSwitchBadge(active) {
    const badge = document.getElementById("kill-switch-badge");
    const statusEl = document.getElementById("system-status");
    const icon = badge ? badge.querySelector("i") : null;
    if (!badge || !statusEl) return;

    if (active) {
        statusEl.textContent = "Kill Switch ON";
        badge.style.color = "var(--danger)";
        badge.style.background = "var(--danger-bg)";
        if (icon) icon.className = "fa-solid fa-triangle-exclamation";
    } else {
        statusEl.textContent = "System Normal";
        badge.style.color = "";
        badge.style.background = "";
        if (icon) icon.className = "fa-solid fa-circle-check";
    }
}

function updateStatusUI(data, formatter) {
    if (!data || data.status === "error") return;

    document.getElementById("equity-val").textContent = formatter(data.equity);
    document.getElementById("equity-sub").textContent = `Prev: ${formatter(data.last_equity)}`;

    const dailyPlEl = document.getElementById("daily-pl-val");
    const dailyPctEl = document.getElementById("daily-pl-pct");
    const plIconBg = document.getElementById("pl-icon-bg");
    const plIcon = document.getElementById("pl-icon");

    dailyPlEl.textContent = `${data.daily_pl >= 0 ? '+' : ''}${formatter(data.daily_pl)}`;
    dailyPctEl.textContent = `${data.daily_pl_pct >= 0 ? '+' : ''}${data.daily_pl_pct.toFixed(2)}%`;

    if (data.daily_pl >= 0) {
        dailyPlEl.style.color = "var(--success)";
        dailyPctEl.className = "kpi-badge positive";
        plIconBg.className = "kpi-icon green";
        plIcon.className = "fa-solid fa-chart-line";
    } else {
        dailyPlEl.style.color = "var(--danger)";
        dailyPctEl.className = "kpi-badge negative";
        plIconBg.className = "kpi-icon red";
        plIcon.className = "fa-solid fa-chart-line-down";
    }

    document.getElementById("buying-power-val").textContent = formatter(data.buying_power);
    document.getElementById("cash-val").textContent = `Cash: ${formatter(data.cash)}`;

    const modeText = document.getElementById("mode-text");
    if (modeText) {
        modeText.textContent = data.paper_trading ? "US Paper (live prices)" : "US LIVE MONEY";
    }

    const marketStatusEl = document.getElementById("market-status");
    const marketBadge = document.getElementById("market-badge");
    if (data.market_open) {
        marketStatusEl.textContent = "US Market Open";
        marketBadge.style.color = "var(--success)";
        marketBadge.style.background = "var(--success-bg)";
    } else {
        marketStatusEl.textContent = "US Market Closed";
        marketBadge.style.color = "var(--warning)";
        marketBadge.style.background = "var(--warning-bg)";
    }

    updateKillSwitchBadge(!!data.kill_switch_active);
    document.getElementById("last-updated").textContent = `Updated: ${data.timestamp.split(' ')[1]}`;
}

function updateIndiaStatusUI(data) {
    if (!data || data.status === "error") return;

    document.getElementById("equity-val").textContent = formatINR(data.equity);
    document.getElementById("equity-sub").textContent = "India Broker Account";

    const dailyPlEl = document.getElementById("daily-pl-val");
    const dailyPctEl = document.getElementById("daily-pl-pct");
    const pl = data.daily_pl != null ? data.daily_pl : 0;
    const plPct = data.daily_pl_pct != null ? data.daily_pl_pct : 0;
    dailyPlEl.textContent = `${pl >= 0 ? '+' : ''}${formatINR(pl)}`;
    dailyPctEl.textContent = `${plPct >= 0 ? '+' : ''}${Number(plPct).toFixed(2)}%`;
    dailyPlEl.style.color = pl >= 0 ? "var(--success)" : "var(--danger)";
    dailyPctEl.className = pl >= 0 ? "kpi-badge positive" : "kpi-badge negative";

    document.getElementById("buying-power-val").textContent = formatINR(data.available_cash);
    document.getElementById("cash-val").textContent = data.paper_trading
        ? "Paper sim (live NSE prices)"
        : `Margin Used: ${formatINR(data.used_margin || 0)}`;

    const modeText = document.getElementById("mode-text");
    if (modeText) {
        modeText.textContent = data.paper_trading
            ? "India Paper (live NSE)"
            : (data.live_armed ? "India LIVE MONEY" : "India SCAN only");
    }

    const marketStatusEl = document.getElementById("market-status");
    const marketBadge = document.getElementById("market-badge");
    if (data.market_open) {
        marketStatusEl.textContent = "NSE India Open";
        marketBadge.style.color = "var(--success)";
        marketBadge.style.background = "var(--success-bg)";
    } else {
        marketStatusEl.textContent = "NSE India Closed";
        marketBadge.style.color = "var(--warning)";
        marketBadge.style.background = "var(--warning-bg)";
    }

    updateKillSwitchBadge(!!data.kill_switch_active);
    document.getElementById("last-updated").textContent = `Updated: ${data.timestamp.split(' ')[1]}`;
}

function renderIndiaDisabledState(msg) {
    document.getElementById("equity-val").textContent = "India Broker Pending";
    document.getElementById("equity-sub").textContent = msg || "Add Dhan credentials to environment";
    document.getElementById("daily-pl-val").textContent = "₹0.00";
    document.getElementById("daily-pl-pct").textContent = "0.00%";
    document.getElementById("buying-power-val").textContent = "₹0.00";
    document.getElementById("cash-val").textContent = "Cash: ₹0.00";

    const marketStatusEl = document.getElementById("market-status");
    const marketBadge = document.getElementById("market-badge");
    marketStatusEl.textContent = "Dhan Keys Needed";
    marketBadge.style.color = "var(--warning)";
    marketBadge.style.background = "var(--warning-bg)";
}

function updatePositionsUI(positions, formatter, closeFnName) {
    const tbody = document.getElementById("positions-tbody");
    document.getElementById("positions-count").textContent = positions.length;
    document.getElementById("table-count-tag").textContent = `${positions.length} Active`;

    if (!positions || positions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No open positions currently held.</td></tr>`;
        return;
    }

    let rowsHtml = "";
    positions.forEach(pos => {
        const plClass = pos.unrealized_pl >= 0 ? "pl-positive" : "pl-negative";
        const plSign = pos.unrealized_pl >= 0 ? "+" : "";

        rowsHtml += `
            <tr>
                <td style="font-weight:700; color:var(--text-main);">${pos.symbol}</td>
                <td>${pos.qty}</td>
                <td>${formatter(pos.avg_entry_price)}</td>
                <td>${formatter(pos.current_price)}</td>
                <td>${formatter(pos.market_value)}</td>
                <td style="color:var(--danger);">${formatter(pos.stop_loss)}</td>
                <td style="color:var(--success);">${formatter(pos.take_profit)}</td>
                <td class="${plClass}">${plSign}${formatter(pos.unrealized_pl)} (${plSign}${pos.unrealized_plpc}%)</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="${closeFnName}('${pos.symbol}')">
                        Close
                    </button>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = rowsHtml;
}

function updateScannerUI(scannerList, formatter) {
    const container = document.getElementById("scanner-container");
    if (!scannerList || scannerList.length === 0) {
        container.innerHTML = `<div class="loading-state">No scanner data yet.</div>`;
        return;
    }

    let cardsHtml = "";
    scannerList.forEach(item => {
        const signalClass = `signal-${item.signal}`;
        const rsiStyle = item.rsi < 35
            ? 'color:var(--success);font-weight:700;'
            : item.rsi > 65
                ? 'color:var(--danger);font-weight:700;'
                : '';

        cardsHtml += `
            <div class="stock-card">
                <div class="stock-head">
                    <span class="stock-sym">${item.symbol}</span>
                    <span class="stock-price">${item.price > 0 ? formatter(item.price) : 'N/A'}</span>
                </div>
                <div class="signal-badge ${signalClass}">${item.signal}</div>
                <div class="indicator-list">
                    <div class="ind-row">
                        <span>14-RSI:</span>
                        <span class="ind-val" style="${rsiStyle}">${item.rsi != null ? item.rsi : '-'}</span>
                    </div>
                    ${item.reason ? `<div class="ind-row"><span>Why:</span><span class="ind-val" style="font-size:0.75rem;">${item.reason}</span></div>` : ''}
                </div>
            </div>
        `;
    });

    container.innerHTML = cardsHtml;
}

async function fetchLogs() {
    try {
        const res = await fetch('/api/logs');
        if (!res.ok) return;
        const data = await res.json();
        const logBox = document.getElementById("log-terminal");
        logBox.innerHTML = "";

        data.logs.forEach(line => {
            const div = document.createElement("div");
            div.className = "log-line";
            if (line.includes("BUY")) div.classList.add("buy");
            else if (line.includes("SELL") || line.includes("CLOSE")) div.classList.add("sell");
            else if (line.includes("CRITICAL") || line.includes("KILL-SWITCH")) div.classList.add("critical");
            else if (line.includes("WARNING") || line.includes("CLOSED")) div.classList.add("warn");
            else div.classList.add("info");
            div.textContent = line;
            logBox.appendChild(div);
        });

        logBox.scrollTop = logBox.scrollHeight;
    } catch (e) {
        console.error("Error fetching logs:", e);
    }
}

async function fetchTrades() {
    const tbody = document.getElementById("trades-tbody");
    if (!tbody) return;
    try {
        const market = currentTab === 'india' ? 'INDIA' : 'US';
        const res = await fetch(`/api/trades?market=${market}&limit=20`);
        if (!res.ok) return;
        const trades = await res.json();
        if (!trades.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No journaled trades yet.</td></tr>`;
            return;
        }
        tbody.innerHTML = trades.map(t => {
            const pnl = t.pnl != null ? Number(t.pnl) : null;
            const plClass = pnl == null ? '' : (pnl >= 0 ? 'pl-positive' : 'pl-negative');
            return `<tr>
                <td>${t.symbol}</td>
                <td>${t.side || t.status || '—'}</td>
                <td>${t.qty ?? '—'}</td>
                <td>${t.entry_price != null ? t.entry_price : '—'}</td>
                <td class="${plClass}">${pnl != null ? (pnl >= 0 ? '+' : '') + pnl.toFixed(2) : '—'}</td>
                <td>${(t.closed_at || t.opened_at || '').toString().slice(0, 19)}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error("Error fetching trades:", e);
    }
}

async function fetchHealth() {
    const el = document.getElementById("health-text");
    if (!el) return;
    try {
        const res = await fetch('/api/health');
        if (!res.ok) return;
        const h = await res.json();
        const usAge = h.us_cycle_age_sec != null ? `${Math.round(h.us_cycle_age_sec)}s` : '—';
        const inAge = h.india_cycle_age_sec != null ? `${Math.round(h.india_cycle_age_sec)}s` : '—';
        el.textContent = `US cycle ${usAge} | IN cycle ${inAge} | 429s ${h.alpaca_429_count || 0}`;
        if (h.us_last_error || h.india_last_error) {
            el.textContent += ' | err';
            el.style.color = 'var(--warning)';
        } else {
            el.style.color = '';
        }
    } catch (e) {
        /* ignore */
    }
}

async function closePosition(symbol) {
    if (!confirm(`Close US position for ${symbol}?`)) return;
    try {
        const res = await fetch(`/api/close_position/${symbol}`, { method: 'POST' });
        const data = await res.json();
        alert(data.message);
        fetchCurrentTabData();
    } catch (e) {
        alert("Failed to close position: " + e);
    }
}

async function closeIndiaPosition(symbol) {
    if (!confirm(`Close India position for ${symbol}?`)) return;
    try {
        const res = await fetch(`/api/india/close_position/${symbol}`, { method: 'POST' });
        const data = await res.json();
        alert(data.message);
        fetchCurrentTabData();
    } catch (e) {
        alert("Failed to close position: " + e);
    }
}

async function toggleKillSwitch() {
    try {
        const res = await fetch('/api/toggle_kill_switch', { method: 'POST' });
        const data = await res.json();
        alert(data.message);
        fetchCurrentTabData();
    } catch (e) {
        alert("Failed to toggle kill switch: " + e);
    }
}

function formatUSD(val) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
}

function formatINR(val) {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(val);
}
