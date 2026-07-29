/* ==========================================================================
   AI Quant Trading Dashboard — Frontend Logic (Chart.js + REST API Polling)
   ========================================================================== */

let equityChart = null;
let allocationChart = null;

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
    initCharts();
    fetchData();
    fetchLogs();
    
    // Auto-refresh every 3 seconds
    setInterval(fetchData, 3000);
    // Refresh logs every 5 seconds
    setInterval(fetchLogs, 5000);
});

/* ── Fetch Main Dashboard Data ─────────────────────────────────────────── */
async function fetchData() {
    try {
        const [statusRes, positionsRes, scannerRes] = await Promise.all([
            fetch('/api/status'),
            fetch('/api/positions'),
            fetch('/api/scanner')
        ]);

        if (statusRes.ok) {
            const status = await statusRes.json();
            updateStatusUI(status);
        }

        if (positionsRes.ok) {
            const positions = await positionsRes.json();
            updatePositionsUI(positions);
        }

        if (scannerRes.ok) {
            const scanner = await scannerRes.json();
            updateScannerUI(scanner);
        }

    } catch (err) {
        console.error("Error fetching dashboard data:", err);
    }
}

/* ── Update Status & KPI Cards ─────────────────────────────────────────── */
function updateStatusUI(data) {
    if (!data || data.status === "error") return;

    // Equity & Daily P&L
    document.getElementById("equity-val").textContent = formatUSD(data.equity);
    document.getElementById("equity-sub").textContent = `Prev: ${formatUSD(data.last_equity)}`;
    
    const dailyPlEl = document.getElementById("daily-pl-val");
    const dailyPctEl = document.getElementById("daily-pl-pct");
    const plIconBg = document.getElementById("pl-icon-bg");
    const plIcon = document.getElementById("pl-icon");

    dailyPlEl.textContent = `${data.daily_pl >= 0 ? '+' : ''}${formatUSD(data.daily_pl)}`;
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

    // Buying Power & Cash
    document.getElementById("buying-power-val").textContent = formatUSD(data.buying_power);
    document.getElementById("cash-val").textContent = `Cash: ${formatUSD(data.cash)}`;

    // Market Status
    const marketStatusEl = document.getElementById("market-status");
    const marketBadge = document.getElementById("market-badge");
    if (data.market_open) {
        marketStatusEl.textContent = "Market Open";
        marketBadge.style.color = "var(--success)";
        marketBadge.style.background = "var(--success-bg)";
    } else {
        marketStatusEl.textContent = "Market Closed";
        marketBadge.style.color = "var(--warning)";
        marketBadge.style.background = "var(--warning-bg)";
    }

    // Kill Switch Status
    const killBadge = document.getElementById("kill-switch-badge");
    const sysStatus = document.getElementById("system-status");
    const killBtn = document.getElementById("kill-switch-btn");

    if (data.kill_switch_active) {
        killBadge.className = "badge status-badge danger";
        sysStatus.textContent = "KILL-SWITCH ACTIVE (Paused)";
        killBtn.textContent = "Reset Kill Switch";
        killBtn.className = "btn btn-secondary";
    } else {
        killBadge.className = "badge status-badge";
        sysStatus.textContent = "System Normal";
        killBtn.innerHTML = '<i class="fa-solid fa-power-off"></i> Kill Switch';
        killBtn.className = "btn btn-danger";
    }

    document.getElementById("last-updated").textContent = `Updated: ${data.timestamp.split(' ')[1]}`;

    // Update Equity Chart
    if (data.equity_history && data.equity_history.length > 0) {
        const labels = data.equity_history.map(pt => pt.timestamp);
        const values = data.equity_history.map(pt => pt.equity);

        equityChart.data.labels = labels;
        equityChart.data.datasets[0].data = values;
        equityChart.update();
    }
}

/* ── Update Positions Table ────────────────────────────────────────────── */
function updatePositionsUI(positions) {
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

        rowsHtml += `
            <tr>
                <td style="font-weight:700; color:var(--text-main);">${pos.symbol}</td>
                <td>${pos.qty}</td>
                <td>${formatUSD(pos.avg_entry_price)}</td>
                <td>${formatUSD(pos.current_price)}</td>
                <td>${formatUSD(pos.market_value)}</td>
                <td style="color:var(--danger);">${formatUSD(pos.stop_loss)}</td>
                <td style="color:var(--success);">${formatUSD(pos.take_profit)}</td>
                <td class="${plClass}">${plSign}${formatUSD(pos.unrealized_pl)} (${plSign}${pos.unrealized_plpc}%)</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="closePosition('${pos.symbol}')">
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
function updateScannerUI(scannerList) {
    const container = document.getElementById("scanner-container");
    if (!scannerList || scannerList.length === 0) return;

    let cardsHtml = "";
    scannerList.forEach(item => {
        const signalClass = `signal-${item.signal}`;

        cardsHtml += `
            <div class="stock-card">
                <div class="stock-head">
                    <span class="stock-sym">${item.symbol}</span>
                    <span class="stock-price">${item.price > 0 ? formatUSD(item.price) : 'N/A'}</span>
                </div>
                <div class="signal-badge ${signalClass}">${item.signal}</div>
                <div class="indicator-list">
                    <div class="ind-row">
                        <span>200-SMA (Trend):</span>
                        <span class="ind-val">${item.sma_200 ? formatUSD(item.sma_200) : '-'}</span>
                    </div>
                    <div class="ind-row">
                        <span>14-RSI:</span>
                        <span class="ind-val" style="${item.rsi < 35 ? 'color:var(--success);font-weight:700;' : item.rsi > 65 ? 'color:var(--danger);font-weight:700;' : ''}">${item.rsi ? item.rsi : '-'}</span>
                    </div>
                    <div class="ind-row">
                        <span>Lower BB:</span>
                        <span class="ind-val">${item.bbl ? formatUSD(item.bbl) : '-'}</span>
                    </div>
                    <div class="ind-row">
                        <span>Upper BB:</span>
                        <span class="ind-val">${item.bbu ? formatUSD(item.bbu) : '-'}</span>
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
                else if (line.includes("WARNING")) div.classList.add("warn");
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
    if (!confirm(`Are you sure you want to close position for ${symbol}?`)) return;
    try {
        const res = await fetch(`/api/close_position/${symbol}`, { method: 'POST' });
        const data = await res.json();
        alert(data.message);
        fetchData();
    } catch (e) {
        alert("Failed to close position: " + e);
    }
}

async function toggleKillSwitch() {
    try {
        const res = await fetch('/api/toggle_kill_switch', { method: 'POST' });
        const data = await res.json();
        alert(data.message);
        fetchData();
    } catch (e) {
        alert("Failed to toggle kill switch: " + e);
    }
}

/* ── Chart Setup ───────────────────────────────────────────────────────── */
function initCharts() {
    // Equity Line Chart
    const ctxEquity = document.getElementById('equityChart').getContext('2d');
    equityChart = new Chart(ctxEquity, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Portfolio Equity ($)',
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

    // Allocation Doughnut Chart
    const ctxAlloc = document.getElementById('allocationChart').getContext('2d');
    allocationChart = new Chart(ctxAlloc, {
        type: 'doughnut',
        data: {
            labels: ['Cash'],
            datasets: [{
                data: [100],
                backgroundColor: ['#1e2d4a', '#3b82f6', '#10b981', '#8b5cf6', '#f59e0b'],
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
