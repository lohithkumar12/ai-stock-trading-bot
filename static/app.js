/* ==========================================================================
   AI Quant Trading Dashboard — Frontend Logic (US + India Markets)
   ========================================================================== */

let currentTab = 'us'; // 'us' | 'india'
let fetchGeneration = 0;
let activeAbort = null;

document.addEventListener("DOMContentLoaded", () => {
    fetchCurrentTabData();
    fetchLogs();
    setInterval(fetchCurrentTabData, 3000);
    setInterval(fetchLogs, 5000);
});

function isStale(gen) {
    return gen !== fetchGeneration;
}

function beginFetch() {
    if (activeAbort) activeAbort.abort();
    activeAbort = new AbortController();
    fetchGeneration += 1;
    return { gen: fetchGeneration, signal: activeAbort.signal };
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
        universeSub.textContent = "Universe: Nifty Large-Caps (Angel One)";
        scannerTitle.innerHTML = '<i class="fa-solid fa-radar"></i> India Strategy Scanner (NSE)';
        positionsTitle.innerHTML = '<i class="fa-solid fa-list-check"></i> India Open Positions';
    }

    clearMarketPanels(tab);
    fetchCurrentTabData();
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

function fetchCurrentTabData() {
    const { gen, signal } = beginFetch();
    if (currentTab === 'us') {
        fetchUSData(gen, signal);
    } else {
        fetchIndiaData(gen, signal);
    }
}

async function fetchUSData(gen, signal) {
    try {
        const [statusRes, positionsRes, scannerRes] = await Promise.all([
            fetch('/api/status', { signal }),
            fetch('/api/positions', { signal }),
            fetch('/api/scanner', { signal })
        ]);
        if (isStale(gen)) return;

        if (statusRes.ok) {
            const status = await statusRes.json();
            if (isStale(gen)) return;
            updateStatusUI(status, formatUSD);
        }

        if (positionsRes.ok) {
            const positions = await positionsRes.json();
            if (isStale(gen)) return;
            updatePositionsUI(positions, formatUSD, 'closePosition');
        }

        if (scannerRes.ok) {
            const scanner = await scannerRes.json();
            if (isStale(gen)) return;
            updateScannerUI(scanner, formatUSD);
        }
    } catch (err) {
        if (err.name === 'AbortError' || isStale(gen)) return;
        console.error("Error fetching US dashboard data:", err);
    }
}

async function fetchIndiaData(gen, signal) {
    try {
        const [statusRes, positionsRes, scannerRes] = await Promise.all([
            fetch('/api/india/status', { signal }),
            fetch('/api/india/positions', { signal }),
            fetch('/api/india/scanner', { signal })
        ]);
        if (isStale(gen)) return;

        if (statusRes.ok) {
            const status = await statusRes.json();
            if (isStale(gen)) return;
            if (status.status === "disabled" || status.status === "error") {
                renderIndiaDisabledState(status.message);
                return;
            }
            updateIndiaStatusUI(status);
        } else {
            renderIndiaDisabledState("Add Angel One keys in environment");
        }

        if (positionsRes.ok) {
            const positions = await positionsRes.json();
            if (isStale(gen)) return;
            updatePositionsUI(positions, formatINR, 'closeIndiaPosition');
        }

        if (scannerRes.ok) {
            const scanner = await scannerRes.json();
            if (isStale(gen)) return;
            updateScannerUI(scanner, formatINR);
        }
    } catch (err) {
        if (err.name === 'AbortError' || isStale(gen)) return;
        console.error("Error fetching India dashboard data:", err);
        renderIndiaDisabledState("Add Angel One keys in environment");
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
    document.getElementById("equity-sub").textContent = "Angel One Account";

    document.getElementById("daily-pl-val").textContent = "₹0.00";
    document.getElementById("daily-pl-pct").textContent = "0.00%";

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
    document.getElementById("equity-val").textContent = "Angel One Pending";
    document.getElementById("equity-sub").textContent = msg || "Add Angel One credentials to environment";
    document.getElementById("daily-pl-val").textContent = "₹0.00";
    document.getElementById("daily-pl-pct").textContent = "0.00%";
    document.getElementById("buying-power-val").textContent = "₹0.00";
    document.getElementById("cash-val").textContent = "Cash: ₹0.00";

    const marketStatusEl = document.getElementById("market-status");
    const marketBadge = document.getElementById("market-badge");
    marketStatusEl.textContent = "Angel One Keys Needed";
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
