/* ==========================================================================
   AI Quant Trading Dashboard — Frontend Logic (US + India Markets)
   ========================================================================== */

let equityChart = null;
let allocationChart = null;
let currentTab = 'us'; // 'us' | 'india' | 'combined'

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
    initCharts();
    fetchCurrentTabData();
    fetchLogs();
    
    // Auto-refresh main tab data every 3 seconds
    setInterval(fetchCurrentTabData, 3000);
    // Refresh logs every 5 seconds
    setInterval(fetchLogs, 5000);
});

/* ── Tab Switcher ───────────────────────────────────────────────────────── */
function switchMarketTab(tab) {
    currentTab = tab;
    
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.add('active');

    const universeSub = document.getElementById("kpi-universe-sub");
    const scannerTitle = document.getElementById("scanner-title");
    const positionsTitle = document.getElementById("positions-title");

    if (tab === 'us') {
        universeSub.textContent = "Universe: US Large-Caps (Alpaca)";
        scannerTitle.innerHTML = '<i class="fa-solid fa-radar"></i> 🇺🇸 US Strategy Scanner (Mean Reversion & Smart DCA)';
        positionsTitle.innerHTML = '<i class="fa-solid fa-list-check"></i> 🇺🇸 US Open Positions';
    } else if (tab === 'india') {
        universeSub.textContent = "Universe: Nifty 50 Large-Caps (Angel One)";
        scannerTitle.innerHTML = '<i class="fa-solid fa-radar"></i> 🇮🇳 India Strategy Scanner (NSE Nifty 50)';
        positionsTitle.innerHTML = '<i class="fa-solid fa-list-check"></i> 🇮🇳 India Open Positions';
    } else if (tab === 'combined') {
        universeSub.textContent = "Universe: US + India Markets";
        scannerTitle.innerHTML = '<i class="fa-solid fa-radar"></i> 🌐 Combined Market Scanner';
        positionsTitle.innerHTML = '<i class="fa-solid fa-list-check"></i> 🌐 Combined Positions';
    }

    fetchCurrentTabData();
}

/* ── Fetch Data Based on Active Tab ────────────────────────────────────── */
function fetchCurrentTabData() {
    if (currentTab === 'us') {
        fetchUSData();
    } else if (currentTab === 'india') {
        fetchIndiaData();
    } else if (currentTab === 'combined') {
        fetchCombinedData();
    }
}

/* ── US Market Fetch ────────────────────────────────────────────────────── */
async function fetchUSData() {
    try {
        const [statusRes, positionsRes, scannerRes] = await Promise.all([
            fetch('/api/status'),
            fetch('/api/positions'),
            fetch('/api/scanner')
        ]);

        if (statusRes.ok) {
            const status = await statusRes.json();
            updateStatusUI(status, '$', formatUSD);
        }

        if (positionsRes.ok) {
            const positions = await positionsRes.json();
            updatePositionsUI(positions, formatUSD, 'closePosition');
        }

        if (scannerRes.ok) {
            const scanner = await scannerRes.json();
            updateScannerUI(scanner, formatUSD);
        }

    } catch (err) {
        console.error("Error fetching US dashboard data:", err);
    }
}

/* ── India Market Fetch ─────────────────────────────────────────────────── */
async function fetchIndiaData() {
    try {
        const [statusRes, positionsRes, scannerRes] = await Promise.all([
            fetch('/api/india/status'),
            fetch('/api/india/positions'),
            fetch('/api/india/scanner')
        ]);

        if (statusRes.ok) {
            const status = await statusRes.json();
            if (status.status === "disabled" || status.status === "error") {
                renderIndiaDisabledState(status.message);
                return;
            }
            updateIndiaStatusUI(status);
        } else {
            renderIndiaDisabledState("Add Angel One keys in Render Environment");
        }

        if (positionsRes.ok) {
            const positions = await positionsRes.json();
            updatePositionsUI(positions, formatINR, 'closeIndiaPosition');
        }

        if (scannerRes.ok) {
            const scanner = await scannerRes.json();
            updateScannerUI(scanner, formatINR);
        }

    } catch (err) {
        console.error("Error fetching India dashboard data:", err);
        renderIndiaDisabledState("Add Angel One keys in Render Environment");
    }
}

/* ── Combined View Fetch ────────────────────────────────────────────────── */
async function fetchCombinedData() {
    try {
        const [combinedRes, usPositionsRes, indiaPositionsRes, usScannerRes, indiaScannerRes] = await Promise.all([
            fetch('/api/combined/status'),
            fetch('/api/positions'),
            fetch('/api/india/positions'),
            fetch('/api/scanner'),
            fetch('/api/india/scanner')
        ]);

        if (combinedRes.ok) {
            const combined = await combinedRes.json();
            updateCombinedStatusUI(combined);
        }

        let allPositions = [];
        if (usPositionsRes.ok) {
            const usPos = await usPositionsRes.json();
            usPos.forEach(p => p.market_tag = '🇺🇸 US');
            allPositions = allPositions.concat(usPos);
        }
        if (indiaPositionsRes.ok) {
            const indiaPos = await indiaPositionsRes.json();
            indiaPos.forEach(p => p.market_tag = '🇮🇳 India');
            allPositions = allPositions.concat(indiaPos);
        }
        updatePositionsUI(allPositions, (val) => formatUSD(val), 'closePosition');

        let allScanner = [];
        if (usScannerRes.ok) {
            const usScan = await usScannerRes.json();
            usScan.forEach(s => s.symbol = `🇺🇸 ${s.symbol}`);
            allScanner = allScanner.concat(usScan);
        }
        if (indiaScannerRes.ok) {
            const indiaScan = await indiaScannerRes.json();
            indiaScan.forEach(s => s.symbol = `🇮🇳 ${s.symbol}`);
            allScanner = allScanner.concat(indiaScan);
        }
        updateScannerUI(allScanner, formatUSD);

    } catch (err) {
        console.error("Error fetching Combined dashboard data:", err);
    }
}

/* ── Update US Status UI ────────────────────────────────────────────────── */
function updateStatusUI(data, currencySymbol, formatter) {
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

    document.getElementById("last-updated").textContent = `Updated: ${data.timestamp.split(' ')[1]}`;

    if (data.equity_history && data.equity_history.length > 0) {
        const labels = data.equity_history.map(pt => pt.timestamp);
        const values = data.equity_history.map(pt => pt.equity);
        equityChart.data.labels = labels;
        equityChart.data.datasets[0].data = values;
        equityChart.update();
    }
}

/* ── Update India Status UI ─────────────────────────────────────────────── */
function updateIndiaStatusUI(data) {
    if (!data || data.status === "error") return;

    document.getElementById("equity-val").textContent = formatINR(data.equity);
    document.getElementById("equity-sub").textContent = `Angel One Account`;

    document.getElementById("daily-pl-val").textContent = "₹0.00";
    document.getElementById("daily-pl-pct").textContent = "0.00%";

    document.getElementById("buying-power-val").textContent = formatINR(data.available_cash);
    document.getElementById("cash-val").textContent = `Margin Used: ${formatINR(data.used_margin)}`;

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

    document.getElementById("last-updated").textContent = `Updated: ${data.timestamp.split(' ')[1]}`;

    if (data.equity_history && data.equity_history.length > 0) {
        const labels = data.equity_history.map(pt => pt.timestamp);
        const values = data.equity_history.map(pt => pt.equity);
        equityChart.data.labels = labels;
        equityChart.data.datasets[0].data = values;
        equityChart.update();
    }
}

/* ── Update Combined Status UI ──────────────────────────────────────────── */
function updateCombinedStatusUI(data) {
    if (!data) return;

    const usEq = data.us ? data.us.equity : 0;
    const indiaEq = data.india ? data.india.equity : 0;

    document.getElementById("equity-val").textContent = `$${usEq.toLocaleString()} | ₹${indiaEq.toLocaleString()}`;
    document.getElementById("equity-sub").textContent = `Aggregated Portfolio`;

    document.getElementById("buying-power-val").textContent = `US: ${formatUSD(data.us ? data.us.cash : 0)}`;
    document.getElementById("cash-val").textContent = `India: ${formatINR(data.india ? data.india.available_cash : 0)}`;

    const marketStatusEl = document.getElementById("market-status");
    marketStatusEl.textContent = "Dual Market Active";
}

function renderIndiaDisabledState(msg) {
    document.getElementById("equity-val").textContent = "Angel One Pending";
    document.getElementById("equity-sub").textContent = msg || "Add Angel One credentials to Render Environment";
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

/* ── Update Positions Table ────────────────────────────────────────────── */
function updatePositionsUI(positions, formatter, closeFnName) {
    const tbody = document.getElementById("positions-tbody");
    document.getElementById("positions-count").textContent = positions.length;
    document.getElementById("table-count-tag").textContent = `${positions.length} Active`;

    if (!positions || positions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No open positions currently held. Bot is scanning for entry dips...</td></tr>`;
        updateAllocationChart([]);
        return;
    }

    let rowsHtml = "";
    positions.forEach(pos => {
        const plClass = pos.unrealized_pl >= 0 ? "pl-positive" : "pl-negative";
        const plSign = pos.unrealized_pl >= 0 ? "+" : "";
        const tag = pos.market_tag ? `<span class="tag" style="margin-right:6px;">${pos.market_tag}</span>` : '';

        rowsHtml += `
            <tr>
                <td style="font-weight:700; color:var(--text-main);">${tag}${pos.symbol}</td>
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
    updateAllocationChart(positions);
}

/* ── Update Scanner Cards ──────────────────────────────────────────────── */
function updateScannerUI(scannerList, formatter) {
    const container = document.getElementById("scanner-container");
    if (!scannerList || scannerList.length === 0) return;

    let cardsHtml = "";
    scannerList.forEach(item => {
        const signalClass = `signal-${item.signal}`;

        cardsHtml += `
            <div class="stock-card">
                <div class="stock-head">
                    <span class="stock-sym">${item.symbol}</span>
                    <span class="stock-price">${item.price > 0 ? formatter(item.price) : 'N/A'}</span>
                </div>
                <div class="signal-badge ${signalClass}">${item.signal}</div>
                <div class="indicator-list">
                    <div class="ind-row">
                        <span>200-SMA:</span>
                        <span class="ind-val">${item.sma_200 ? formatter(item.sma_200) : '-'}</span>
                    </div>
                    <div class="ind-row">
                        <span>14-RSI:</span>
                        <span class="ind-val" style="${item.rsi < 35 ? 'color:var(--success);font-weight:700;' : item.rsi > 65 ? 'color:var(--danger);font-weight:700;' : ''}">${item.rsi ? item.rsi : '-'}</span>
                    </div>
                    <div class="ind-row">
                        <span>Lower BB:</span>
                        <span class="ind-val">${item.bbl ? formatter(item.bbl) : '-'}</span>
                    </div>
                    <div class="ind-row">
                        <span>Upper BB:</span>
                        <span class="ind-val">${item.bbu ? formatter(item.bbu) : '-'}</span>
                    </div>
                </div>
            </div>
        `;
    });

    container.innerHTML = cardsHtml;
}

/* ── Update Bot Log Window ─────────────────────────────────────────────── */
async function fetchLogs() {
    try {
        const res = await fetch('/api/logs');
        if (res.ok) {
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
        }
    } catch (e) {
        console.error("Error fetching logs:", e);
    }
}

/* ── Actions ────────────────────────────────────────────────────────────── */
async function closePosition(symbol) {
    if (!confirm(`Are you sure you want to close US position for ${symbol}?`)) return;
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
    if (!confirm(`Are you sure you want to close India position for ${symbol}?`)) return;
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

/* ── Chart Setup ───────────────────────────────────────────────────────── */
function initCharts() {
    const ctxEquity = document.getElementById('equityChart').getContext('2d');
    equityChart = new Chart(ctxEquity, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Portfolio Equity',
                data: [],
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.08)',
                fill: true,
                tension: 0.3,
                borderWidth: 2,
                pointRadius: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#8a99ad' } },
                y: { grid: { color: '#1e2d4a' }, ticks: { color: '#8a99ad' } }
            }
        }
    });

    const ctxAlloc = document.getElementById('allocationChart').getContext('2d');
    allocationChart = new Chart(ctxAlloc, {
        type: 'doughnut',
        data: {
            labels: ['Cash'],
            datasets: [{
                data: [100],
                backgroundColor: ['#1e2d4a', '#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#ff9933'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#8a99ad', boxWidth: 12 } }
            }
        }
    });
}

function updateAllocationChart(positions) {
    if (!allocationChart) return;

    if (!positions || positions.length === 0) {
        allocationChart.data.labels = ['Cash'];
        allocationChart.data.datasets[0].data = [100];
        allocationChart.update();
        return;
    }

    const labels = positions.map(p => p.symbol);
    const data = positions.map(p => p.market_value);
    
    allocationChart.data.labels = labels;
    allocationChart.data.datasets[0].data = data;
    allocationChart.update();
}

function formatUSD(val) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
}

function formatINR(val) {
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(val);
}
