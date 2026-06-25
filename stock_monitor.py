"""
╔═════════════════════════════════════════════════════════╗
║         REAL-TIME STOCK MONITOR - University Project    ║
║         OS Concepts: Threads, Mutex, Synchronization    ║
║         Language: Python | GUI: tkinter + matplotlib    ║
║         NEW: CSV Logger Thread + Export Feature         ║
╚═════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import ttk, font, messagebox
import threading
import time
import random
import queue
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.patches as mpatches
from collections import deque
import math
import csv
import os

# ─────────────────────────────────────────────
#  SHARED RESOURCES  (Protected by Mutex/Locks)
# ─────────────────────────────────────────────
stock_lock     = threading.Lock()
alert_lock     = threading.Lock()
portfolio_lock = threading.Lock()
csv_lock       = threading.Lock()
log_queue      = queue.Queue()

CSV_FILENAME = "stock_data.csv"
CSV_HEADERS  = ["Timestamp", "Symbol", "Company", "Price", "Change", "Change_%"]

# ─────────────────────────────────────────────
#  STOCK DATA MODEL
# ─────────────────────────────────────────────
STOCKS = {
    "AAPL":  {"name": "Apple Inc.",       "price": 182.50, "history": deque(maxlen=60), "color": "#00d4ff"},
    "GOOGL": {"name": "Alphabet Inc.",    "price": 141.80, "history": deque(maxlen=60), "color": "#ff6b35"},
    "TSLA":  {"name": "Tesla Inc.",       "price": 248.50, "history": deque(maxlen=60), "color": "#ff2d55"},
    "AMZN":  {"name": "Amazon.com",       "price": 178.25, "history": deque(maxlen=60), "color": "#ffd60a"},
    "MSFT":  {"name": "Microsoft Corp.",  "price": 374.00, "history": deque(maxlen=60), "color": "#30d158"},
    "NVDA":  {"name": "NVIDIA Corp.",     "price": 495.00, "history": deque(maxlen=60), "color": "#bf5af2"},
}

alerts = []
portfolio = {}
race_condition_demo = {"counter": 0, "safe_counter": 0}


# ═══════════════════════════════════════════════════════════════
#  THREAD 5: CSV Logger Thread
# ═══════════════════════════════════════════════════════════════
class CSVLoggerThread(threading.Thread):
    def __init__(self, stop_event, interval=10):
        super().__init__(daemon=True, name="CSVLoggerThread")
        self.stop_event   = stop_event
        self.interval     = interval
        self.rows_written = 0

        if not os.path.exists(CSV_FILENAME):
            with open(CSV_FILENAME, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_HEADERS)
            log_queue.put(("INFO", f"CSVLoggerThread: created '{CSV_FILENAME}'"))

    def run(self):
        log_queue.put(("INFO", f"CSVLoggerThread started — saving every {self.interval}s"))
        while not self.stop_event.is_set():
            time.sleep(self.interval)

            with stock_lock:
                snapshot = {
                    s: {"name": d["name"], "price": d["price"], "history": list(d["history"])}
                    for s, d in STOCKS.items()
                }

            with csv_lock:
                with open(CSV_FILENAME, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for symbol, data in snapshot.items():
                        price   = data["price"]
                        history = data["history"]
                        if len(history) >= 2:
                            prev_price = history[-2][1]
                            change     = round(price - prev_price, 4)
                            change_pct = round((change / prev_price) * 100, 4)
                        else:
                            change = change_pct = 0.0
                        writer.writerow([ts, symbol, data["name"], price, change, change_pct])
                        self.rows_written += 1

            log_queue.put(("INFO", f"CSVLoggerThread: saved {len(snapshot)} rows → total={self.rows_written}"))

        log_queue.put(("INFO", "CSVLoggerThread stopped."))


# ─────────────────────────────────────────────────────────────
#  THREAD 1: Stock Price Updater
# ─────────────────────────────────────────────────────────────
class StockUpdaterThread(threading.Thread):
    def __init__(self, update_callback, stop_event):
        super().__init__(daemon=True, name="StockUpdaterThread")
        self.update_callback = update_callback
        self.stop_event      = stop_event
        self.update_count    = 0

    def run(self):
        log_queue.put(("INFO", "StockUpdaterThread started — monitoring prices..."))
        while not self.stop_event.is_set():
            with stock_lock:
                for symbol, data in STOCKS.items():
                    old_price  = data["price"]
                    change_pct = random.gauss(0, 0.003)
                    if random.random() < 0.02:
                        change_pct += random.choice([-1, 1]) * random.uniform(0.01, 0.04)
                    new_price      = max(1.0, old_price * (1 + change_pct))
                    data["price"]  = round(new_price, 2)
                    data["history"].append((datetime.now(), new_price))
                    self.update_count += 1
            self.update_callback()
            time.sleep(1.0)
        log_queue.put(("INFO", "StockUpdaterThread stopped."))


# ─────────────────────────────────────────────────────────────
#  THREAD 2: Alert Checker
# ─────────────────────────────────────────────────────────────
class AlertCheckerThread(threading.Thread):
    def __init__(self, alert_callback, stop_event):
        super().__init__(daemon=True, name="AlertCheckerThread")
        self.alert_callback = alert_callback
        self.stop_event     = stop_event
        self.thresholds = {
            "TSLA":  {"high": 260,  "low": 235},
            "AAPL":  {"high": 190,  "low": 175},
            "NVDA":  {"high": 520,  "low": 470},
            "GOOGL": {"high": 150,  "low": 135},
            "AMZN":  {"high": 190,  "low": 165},
            "MSFT":  {"high": 390,  "low": 360},
        }

    def run(self):
        log_queue.put(("INFO", "AlertCheckerThread started — watching thresholds..."))
        while not self.stop_event.is_set():
            with stock_lock:
                prices = {s: d["price"] for s, d in STOCKS.items()}
            with alert_lock:
                for symbol, thres in self.thresholds.items():
                    price = prices.get(symbol, 0)
                    if price >= thres["high"]:
                        msg = f"🔺 {symbol} HIGH ALERT: ${price:.2f} ≥ ${thres['high']}"
                        if not alerts or alerts[-1] != msg:
                            alerts.append(msg)
                            self.alert_callback(msg, "high")
                            log_queue.put(("ALERT", msg))
                    elif price <= thres["low"]:
                        msg = f"🔻 {symbol} LOW ALERT: ${price:.2f} ≤ ${thres['low']}"
                        if not alerts or alerts[-1] != msg:
                            alerts.append(msg)
                            self.alert_callback(msg, "low")
                            log_queue.put(("ALERT", msg))
            time.sleep(2.0)
        log_queue.put(("INFO", "AlertCheckerThread stopped."))


# ─────────────────────────────────────────────────────────────
#  THREAD 3: Portfolio Value Calculator
# ─────────────────────────────────────────────────────────────
class PortfolioThread(threading.Thread):
    def __init__(self, portfolio_callback, stop_event):
        super().__init__(daemon=True, name="PortfolioThread")
        self.portfolio_callback = portfolio_callback
        self.stop_event         = stop_event

    def run(self):
        log_queue.put(("INFO", "PortfolioThread started — calculating value..."))
        while not self.stop_event.is_set():
            total     = 0.0
            breakdown = {}
            with portfolio_lock:
                port_copy = dict(portfolio)
            with stock_lock:
                for symbol, qty in port_copy.items():
                    if symbol in STOCKS:
                        price            = STOCKS[symbol]["price"]
                        value            = price * qty
                        breakdown[symbol] = (qty, price, value)
                        total            += value
            self.portfolio_callback(total, breakdown)
            time.sleep(1.5)
        log_queue.put(("INFO", "PortfolioThread stopped."))


# ─────────────────────────────────────────────────────────────
#  THREAD 4: Race Condition Demonstrator
# ─────────────────────────────────────────────────────────────
class RaceConditionThread(threading.Thread):
    def __init__(self, symbol, use_lock, result_callback):
        super().__init__(daemon=True, name=f"RaceThread-{symbol}")
        self.symbol          = symbol
        self.use_lock        = use_lock
        self.result_callback = result_callback
        self._lock           = threading.Lock()

    def run(self):
        for _ in range(1000):
            if self.use_lock:
                with self._lock:
                    race_condition_demo["safe_counter"] += 1
            else:
                val = race_condition_demo["counter"]
                time.sleep(0.000001)
                race_condition_demo["counter"] = val + 1
        self.result_callback(self.symbol, self.use_lock)


# ═══════════════════════════════════════════════════════════════
#  MAIN APPLICATION GUI
# ═══════════════════════════════════════════════════════════════
class StockMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📈 Real-Time Stock Monitor — OS Threading Project")
        self.root.geometry("1400x900")
        self.root.configure(bg="#0a0a0f")
        self.root.minsize(1200, 750)

        self.stop_event      = threading.Event()
        self.selected_stock  = tk.StringVar(value="AAPL")
        self.threads_running = False
        self.alert_count     = 0

        for symbol, data in STOCKS.items():
            base = data["price"]
            for i in range(30):
                t = datetime.now()
                p = base * (1 + random.gauss(0, 0.005))
                data["history"].append((t, round(p, 2)))

        self._build_ui()
        self._start_threads()
        self._poll_logs()

    # ── BUILD FULL UI ──────────────────────────────────────────
    def _build_ui(self):
        header = tk.Frame(self.root, bg="#0d0d1a", height=65)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(header, text="📈  REAL-TIME STOCK MONITOR",
                 font=("Courier New", 22, "bold"),
                 fg="#00d4ff", bg="#0d0d1a").pack(side=tk.LEFT, padx=20, pady=15)

        self.clock_label = tk.Label(header, text="", font=("Courier New", 13),
                                    fg="#888", bg="#0d0d1a")
        self.clock_label.pack(side=tk.RIGHT, padx=20)
        self._update_clock()

        self.thread_status = tk.Label(header, text="● THREADS: STOPPED",
                                      font=("Courier New", 11, "bold"),
                                      fg="#ff2d55", bg="#0d0d1a")
        self.thread_status.pack(side=tk.RIGHT, padx=20)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TNotebook", background="#0a0a0f", borderwidth=0)
        style.configure("Dark.TNotebook.Tab",
                        background="#1a1a2e", foreground="#aaa",
                        font=("Courier New", 11, "bold"), padding=[15, 8])
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", "#00d4ff")],
                  foreground=[("selected", "#000")])

        self.notebook = ttk.Notebook(self.root, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tab_dashboard = tk.Frame(self.notebook, bg="#0a0a0f")
        self.tab_chart     = tk.Frame(self.notebook, bg="#0a0a0f")
        self.tab_portfolio = tk.Frame(self.notebook, bg="#0a0a0f")
        self.tab_alerts    = tk.Frame(self.notebook, bg="#0a0a0f")
        self.tab_race      = tk.Frame(self.notebook, bg="#0a0a0f")
        self.tab_threads   = tk.Frame(self.notebook, bg="#0a0a0f")
        self.tab_csv       = tk.Frame(self.notebook, bg="#0a0a0f")

        self.notebook.add(self.tab_dashboard, text="  📊 Dashboard  ")
        self.notebook.add(self.tab_chart,     text="  📉 Live Chart  ")
        self.notebook.add(self.tab_portfolio, text="  💼 Portfolio  ")
        self.notebook.add(self.tab_alerts,    text="  🚨 Alerts  ")
        self.notebook.add(self.tab_race,      text="  ⚡ Race Condition  ")
        self.notebook.add(self.tab_threads,   text="  🔧 Thread Monitor  ")
        self.notebook.add(self.tab_csv,       text="  💾 CSV Logger  ")

        self._build_dashboard()
        self._build_chart_tab()
        self._build_portfolio_tab()
        self._build_alerts_tab()
        self._build_race_tab()
        self._build_threads_tab()
        self._build_csv_tab()

    # ── DASHBOARD TAB ──────────────────────────────────────────
    def _build_dashboard(self):
        tk.Label(self.tab_dashboard, text="LIVE MARKET OVERVIEW",
                 font=("Courier New", 14, "bold"), fg="#00d4ff", bg="#0a0a0f"
                 ).pack(pady=(15, 10))

        self.cards_frame = tk.Frame(self.tab_dashboard, bg="#0a0a0f")
        self.cards_frame.pack(fill=tk.X, padx=20)

        self.stock_cards = {}
        for i, symbol in enumerate(STOCKS):
            card = self._make_stock_card(self.cards_frame, symbol)
            card.grid(row=i // 3, column=i % 3, padx=8, pady=8, sticky="nsew")
            self.stock_cards[symbol] = card

        for c in range(3):
            self.cards_frame.columnconfigure(c, weight=1)

        summary = tk.Frame(self.tab_dashboard, bg="#0d0d1a", height=50)
        summary.pack(fill=tk.X, padx=20, pady=10)
        summary.pack_propagate(False)

        self.market_summary = tk.Label(summary, text="Market loading...",
                                       font=("Courier New", 11),
                                       fg="#aaa", bg="#0d0d1a")
        self.market_summary.pack(expand=True)

    def _make_stock_card(self, parent, symbol):
        data  = STOCKS[symbol]
        color = data["color"]

        frame = tk.Frame(parent, bg="#12121f", relief=tk.FLAT,
                         highlightthickness=1, highlightbackground=color)

        tk.Label(frame, text=symbol, font=("Courier New", 18, "bold"),
                 fg=color, bg="#12121f").pack(anchor=tk.W, padx=15, pady=(12, 0))
        tk.Label(frame, text=data["name"], font=("Courier New", 9),
                 fg="#555", bg="#12121f").pack(anchor=tk.W, padx=15)

        price_lbl = tk.Label(frame, text=f"${data['price']:.2f}",
                             font=("Courier New", 22, "bold"),
                             fg="#fff", bg="#12121f")
        price_lbl.pack(anchor=tk.W, padx=15, pady=(5, 0))

        change_lbl = tk.Label(frame, text="▲ 0.00  (+0.00%)",
                              font=("Courier New", 10),
                              fg="#30d158", bg="#12121f")
        change_lbl.pack(anchor=tk.W, padx=15, pady=(0, 12))

        frame.price_label  = price_lbl
        frame.change_label = change_lbl
        frame.prev_price   = data["price"]
        return frame

    # ── CHART TAB ──────────────────────────────────────────────
    def _build_chart_tab(self):
        ctrl = tk.Frame(self.tab_chart, bg="#0a0a0f")
        ctrl.pack(fill=tk.X, padx=20, pady=10)

        tk.Label(ctrl, text="SELECT STOCK:", font=("Courier New", 11, "bold"),
                 fg="#00d4ff", bg="#0a0a0f").pack(side=tk.LEFT, padx=5)

        for symbol in STOCKS:
            color = STOCKS[symbol]["color"]
            tk.Radiobutton(ctrl, text=symbol, variable=self.selected_stock,
                           value=symbol,
                           font=("Courier New", 11, "bold"),
                           fg=color, bg="#0a0a0f",
                           selectcolor="#1a1a2e",
                           activebackground="#0a0a0f",
                           activeforeground=color,
                           indicatoron=False, width=6, relief=tk.FLAT,
                           highlightthickness=1,
                           highlightbackground=color).pack(side=tk.LEFT, padx=4)

        self.fig = Figure(figsize=(12, 5), dpi=96, facecolor="#0a0a0f")
        self.ax  = self.fig.add_subplot(111)
        self.ax.set_facecolor("#0d0d1a")
        self.fig.tight_layout(pad=2)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.tab_chart)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        self.ani = animation.FuncAnimation(self.fig, self._animate_chart,
                                           interval=1000, cache_frame_data=False)

    def _animate_chart(self, frame):
        symbol = self.selected_stock.get()
        self.ax.clear()
        self.ax.set_facecolor("#0d0d1a")

        with stock_lock:
            history = list(STOCKS[symbol]["history"])
            color   = STOCKS[symbol]["color"]
            name    = STOCKS[symbol]["name"]

        if len(history) < 2:
            return

        prices = [p for _, p in history]
        x      = list(range(len(prices)))

        self.ax.fill_between(x, prices, min(prices) * 0.998, color=color, alpha=0.15)
        self.ax.plot(x, prices, color=color, linewidth=2.5, zorder=5)
        self.ax.scatter([x[-1]], [prices[-1]], color=color, s=60, zorder=6)

        self.ax.annotate(f"${prices[-1]:.2f}",
                         xy=(x[-1], prices[-1]),
                         xytext=(x[-1] - 3, prices[-1] + (max(prices) - min(prices)) * 0.05),
                         color=color, fontsize=11, fontweight="bold",
                         fontfamily="Courier New")

        self.ax.set_title(f"{symbol} — {name}", color="#fff", fontsize=13,
                          fontfamily="Courier New", pad=10)
        self.ax.set_xlabel("Time (seconds)", color="#555", fontfamily="Courier New")
        self.ax.set_ylabel("Price (USD)",    color="#555", fontfamily="Courier New")
        self.ax.tick_params(colors="#555")
        for spine in self.ax.spines.values():
            spine.set_edgecolor("#222")
        self.ax.grid(True, color="#1a1a2e", linewidth=0.5)
        self.fig.tight_layout(pad=2)

    # ── PORTFOLIO TAB ──────────────────────────────────────────
    def _build_portfolio_tab(self):
        left  = tk.Frame(self.tab_portfolio, bg="#0a0a0f")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=15)

        right = tk.Frame(self.tab_portfolio, bg="#0a0a0f", width=340)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=20, pady=15)
        right.pack_propagate(False)

        tk.Label(left, text="💼 MY PORTFOLIO", font=("Courier New", 14, "bold"),
                 fg="#00d4ff", bg="#0a0a0f").pack(anchor=tk.W, pady=(0, 10))

        add_frame = tk.Frame(left, bg="#12121f",
                             highlightthickness=1, highlightbackground="#222")
        add_frame.pack(fill=tk.X, pady=5)

        inner = tk.Frame(add_frame, bg="#12121f")
        inner.pack(padx=15, pady=12)

        tk.Label(inner, text="Symbol:", font=("Courier New", 10),
                 fg="#aaa", bg="#12121f").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.port_symbol = ttk.Combobox(inner, values=list(STOCKS.keys()),
                                        width=8, state="readonly",
                                        font=("Courier New", 10))
        self.port_symbol.set("AAPL")
        self.port_symbol.grid(row=0, column=1, padx=8, pady=3)

        tk.Label(inner, text="Qty:", font=("Courier New", 10),
                 fg="#aaa", bg="#12121f").grid(row=0, column=2, sticky=tk.W)
        self.port_qty = tk.Entry(inner, width=6, font=("Courier New", 10),
                                 bg="#1a1a2e", fg="#fff", insertbackground="#fff",
                                 relief=tk.FLAT)
        self.port_qty.insert(0, "10")
        self.port_qty.grid(row=0, column=3, padx=8)

        tk.Button(inner, text="ADD", font=("Courier New", 10, "bold"),
                  fg="#000", bg="#00d4ff", relief=tk.FLAT, padx=10,
                  command=self._add_to_portfolio).grid(row=0, column=4, padx=5)

        tk.Button(inner, text="CLEAR", font=("Courier New", 10, "bold"),
                  fg="#fff", bg="#ff2d55", relief=tk.FLAT, padx=10,
                  command=self._clear_portfolio).grid(row=0, column=5, padx=5)

        cols = ("Symbol", "Qty", "Price", "Value", "Change")
        self.port_tree = ttk.Treeview(left, columns=cols, show="headings",
                                      height=8, style="Dark.Treeview")
        style = ttk.Style()
        style.configure("Dark.Treeview",
                        background="#12121f", foreground="#ccc",
                        fieldbackground="#12121f", rowheight=28,
                        font=("Courier New", 10))
        style.configure("Dark.Treeview.Heading",
                        background="#1a1a2e", foreground="#00d4ff",
                        font=("Courier New", 10, "bold"))

        for c in cols:
            self.port_tree.heading(c, text=c)
            self.port_tree.column(c, width=100, anchor=tk.CENTER)
        self.port_tree.pack(fill=tk.BOTH, expand=True, pady=10)

        tk.Label(right, text="PORTFOLIO VALUE", font=("Courier New", 12, "bold"),
                 fg="#ffd60a", bg="#0a0a0f").pack(pady=(0, 10))

        self.total_value_label = tk.Label(right, text="$0.00",
                                          font=("Courier New", 32, "bold"),
                                          fg="#30d158", bg="#0a0a0f")
        self.total_value_label.pack(pady=10)

        tk.Label(right,
                 text="Calculated by PortfolioThread\n(Thread #3 — runs every 1.5s)",
                 font=("Courier New", 9), fg="#444", bg="#0a0a0f",
                 justify=tk.CENTER).pack(pady=5)

        self.port_breakdown = tk.Text(right, bg="#12121f", fg="#aaa",
                                      font=("Courier New", 9),
                                      relief=tk.FLAT, height=20, state=tk.DISABLED)
        self.port_breakdown.pack(fill=tk.BOTH, expand=True, pady=10)

    def _add_to_portfolio(self):
        symbol = self.port_symbol.get()
        try:
            qty = int(self.port_qty.get())
        except ValueError:
            return
        with portfolio_lock:
            portfolio[symbol] = portfolio.get(symbol, 0) + qty
        log_queue.put(("INFO", f"Portfolio updated: +{qty} {symbol}"))

    def _clear_portfolio(self):
        with portfolio_lock:
            portfolio.clear()
        self.total_value_label.config(text="$0.00")

    def _update_portfolio_ui(self, total, breakdown):
        self.total_value_label.config(text=f"${total:,.2f}")
        for row in self.port_tree.get_children():
            self.port_tree.delete(row)
        self.port_breakdown.config(state=tk.NORMAL)
        self.port_breakdown.delete("1.0", tk.END)
        for sym, (qty, price, val) in breakdown.items():
            color_tag = "green" if val > 0 else "red"
            self.port_tree.insert("", tk.END,
                values=(sym, qty, f"${price:.2f}", f"${val:,.2f}", ""),
                tags=(color_tag,))
            self.port_breakdown.insert(tk.END,
                f"{sym:5s} × {qty:4d} @ ${price:.2f}\n     = ${val:,.2f}\n\n")
        self.port_tree.tag_configure("green", foreground="#30d158")
        self.port_breakdown.config(state=tk.DISABLED)

    # ── ALERTS TAB ─────────────────────────────────────────────
    def _build_alerts_tab(self):
        tk.Label(self.tab_alerts, text="🚨 PRICE ALERTS",
                 font=("Courier New", 14, "bold"),
                 fg="#ff2d55", bg="#0a0a0f").pack(pady=15)

        info = tk.Frame(self.tab_alerts, bg="#12121f",
                        highlightthickness=1, highlightbackground="#ff2d55")
        info.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(info,
                 text="AlertCheckerThread monitors all stocks and fires when price crosses thresholds.\n"
                      "Uses TWO locks: stock_lock (read) + alert_lock (write) — no deadlock by design.",
                 font=("Courier New", 9), fg="#888", bg="#12121f",
                 justify=tk.LEFT, padx=15, pady=8).pack(anchor=tk.W)

        self.alert_count_label = tk.Label(self.tab_alerts, text="Total Alerts: 0",
                                          font=("Courier New", 11, "bold"),
                                          fg="#ffd60a", bg="#0a0a0f")
        self.alert_count_label.pack(pady=5)

        self.alert_box = tk.Text(self.tab_alerts, bg="#0d0d1a", fg="#ff6b35",
                                 font=("Courier New", 11),
                                 relief=tk.FLAT, padx=10, pady=10)
        self.alert_box.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        self.alert_box.insert(tk.END, "Waiting for price alerts...\n")
        self.alert_box.config(state=tk.DISABLED)

    def _add_alert(self, msg, level):
        self.alert_count += 1
        self.alert_count_label.config(text=f"Total Alerts: {self.alert_count}")
        self.alert_box.config(state=tk.NORMAL)
        ts    = datetime.now().strftime("%H:%M:%S")
        color = "#ff2d55" if level == "high" else "#ffd60a"
        tag   = f"alert_{self.alert_count}"
        self.alert_box.insert(tk.END, f"[{ts}] {msg}\n", tag)
        self.alert_box.tag_config(tag, foreground=color)
        self.alert_box.see(tk.END)
        self.alert_box.config(state=tk.DISABLED)

    # ── RACE CONDITION TAB ─────────────────────────────────────
    def _build_race_tab(self):
        tk.Label(self.tab_race, text="⚡ RACE CONDITION DEMONSTRATION",
                 font=("Courier New", 14, "bold"),
                 fg="#ffd60a", bg="#0a0a0f").pack(pady=15)

        info = tk.Frame(self.tab_race, bg="#12121f",
                        highlightthickness=1, highlightbackground="#ffd60a")
        info.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(info,
                 text="Two threads increment a counter 1000 times each.\n"
                      "WITHOUT lock  → Race Condition → result < 2000 (data corruption!)\n"
                      "WITH Mutex    → Synchronized   → result = 2000 (always correct)",
                 font=("Courier New", 10), fg="#aaa", bg="#12121f",
                 justify=tk.LEFT, padx=15, pady=10).pack(anchor=tk.W)

        btn_frame = tk.Frame(self.tab_race, bg="#0a0a0f")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="▶  RUN WITHOUT LOCK (Race Condition)",
                  font=("Courier New", 11, "bold"),
                  fg="#fff", bg="#ff2d55", relief=tk.FLAT, padx=15, pady=8,
                  command=lambda: self._run_race(False)).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="🔒  RUN WITH MUTEX (Safe)",
                  font=("Courier New", 11, "bold"),
                  fg="#000", bg="#30d158", relief=tk.FLAT, padx=15, pady=8,
                  command=lambda: self._run_race(True)).pack(side=tk.LEFT, padx=10)

        self.race_result = tk.Label(self.tab_race, text="",
                                    font=("Courier New", 14), fg="#fff", bg="#0a0a0f",
                                    justify=tk.CENTER)
        self.race_result.pack(pady=20)

        self.race_log = tk.Text(self.tab_race, bg="#0d0d1a", fg="#aaa",
                                font=("Courier New", 10),
                                relief=tk.FLAT, height=12, padx=10, pady=10)
        self.race_log.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

    def _run_race(self, use_lock):
        key   = "safe_counter" if use_lock else "counter"
        race_condition_demo[key] = 0
        label = "WITH MUTEX" if use_lock else "WITHOUT LOCK"
        self.race_log.insert(tk.END, f"\n▶ Starting {label}...\n")
        completed = [0]

        def done(sym, locked):
            completed[0] += 1
            if completed[0] == 2:
                result   = race_condition_demo["safe_counter" if locked else "counter"]
                expected = 2000
                status   = "✅ CORRECT" if result == expected else "❌ RACE CONDITION DETECTED"
                color    = "#30d158" if result == expected else "#ff2d55"
                self.race_result.config(
                    text=f"{label}\nResult: {result} / Expected: {expected}\n{status}",
                    fg=color)
                self.race_log.insert(tk.END,
                    f"  Counter = {result} (expected {expected})\n"
                    f"  {'No data corruption — Mutex worked!' if result == expected else 'DATA CORRUPTION — threads overwrote each other!'}\n")
                self.race_log.see(tk.END)

        RaceConditionThread("T1", use_lock, done).start()
        RaceConditionThread("T2", use_lock, done).start()

    # ── THREAD MONITOR TAB ─────────────────────────────────────
    def _build_threads_tab(self):
        tk.Label(self.tab_threads, text="🔧 THREAD MONITOR & CONSOLE",
                 font=("Courier New", 14, "bold"),
                 fg="#30d158", bg="#0a0a0f").pack(pady=15)

        thread_info = [
            ("Thread 1", "StockUpdaterThread",   "Updates all 6 stock prices every 1s",        "stock_lock (Mutex)"),
            ("Thread 2", "AlertCheckerThread",   "Checks thresholds every 2s",                  "stock_lock + alert_lock"),
            ("Thread 3", "PortfolioThread",      "Recalculates portfolio value every 1.5s",     "portfolio_lock + stock_lock"),
            ("Thread 4", "RaceConditionDemo×2",  "Demonstrates unsafe vs safe counter update",  "Optional Mutex"),
            ("Thread 5", "CSVLoggerThread",      "Saves stock prices to CSV every 10s",         "stock_lock + csv_lock"),
        ]

        tbl = tk.Frame(self.tab_threads, bg="#0a0a0f")
        tbl.pack(fill=tk.X, padx=20, pady=5)

        headers = ["#", "Thread Name", "Purpose", "Synchronization"]
        widths  = [4, 22, 35, 25]
        for c, (h, w) in enumerate(zip(headers, widths)):
            tk.Label(tbl, text=h, font=("Courier New", 10, "bold"),
                     fg="#00d4ff", bg="#1a1a2e",
                     width=w, anchor=tk.W, padx=5, pady=5
                     ).grid(row=0, column=c, sticky=tk.EW, padx=1, pady=1)

        for r, row_data in enumerate(thread_info, 1):
            for c, (val, w) in enumerate(zip(row_data, widths)):
                tk.Label(tbl, text=val, font=("Courier New", 9),
                         fg="#ccc", bg="#12121f",
                         width=w, anchor=tk.W, padx=5, pady=6
                         ).grid(row=r, column=c, sticky=tk.EW, padx=1, pady=1)

        status_frame = tk.Frame(self.tab_threads, bg="#0a0a0f")
        status_frame.pack(fill=tk.X, padx=20, pady=5)

        self.thread_indicators = {}
        for sym in ["StockUpdater", "AlertChecker", "Portfolio", "CSVLogger"]:
            f   = tk.Frame(status_frame, bg="#12121f",
                           highlightthickness=1, highlightbackground="#222")
            f.pack(side=tk.LEFT, padx=5, pady=5)
            dot = tk.Label(f, text="●", font=("Courier New", 14),
                           fg="#ff2d55", bg="#12121f")
            dot.pack(side=tk.LEFT, padx=(10, 3), pady=5)
            tk.Label(f, text=sym, font=("Courier New", 9),
                     fg="#888", bg="#12121f").pack(side=tk.LEFT, padx=(0, 10))
            self.thread_indicators[sym] = dot

        tk.Label(self.tab_threads, text="CONSOLE LOG",
                 font=("Courier New", 10, "bold"),
                 fg="#555", bg="#0a0a0f").pack(anchor=tk.W, padx=20)

        self.console = tk.Text(self.tab_threads, bg="#050508", fg="#00d4ff",
                               font=("Courier New", 9),
                               relief=tk.FLAT, padx=10, pady=10)
        self.console.pack(fill=tk.BOTH, expand=True, padx=20, pady=(2, 15))

    # ── CSV LOGGER TAB ─────────────────────────────────────────
    def _build_csv_tab(self):
        tk.Label(self.tab_csv, text="💾 CSV DATA LOGGER",
                 font=("Courier New", 14, "bold"),
                 fg="#30d158", bg="#0a0a0f").pack(pady=15)

        info = tk.Frame(self.tab_csv, bg="#12121f",
                        highlightthickness=1, highlightbackground="#30d158")
        info.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(info,
                 text=f"CSVLoggerThread (Thread #5) automatically saves all stock prices to '{CSV_FILENAME}' every 10 seconds.\n"
                       "Uses stock_lock (read) + csv_lock (write) to prevent data corruption.",
                 font=("Courier New", 9), fg="#888", bg="#12121f",
                 justify=tk.LEFT, padx=15, pady=8).pack(anchor=tk.W)

        btn_frame = tk.Frame(self.tab_csv, bg="#0a0a0f")
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="💾  EXPORT NOW",
                  font=("Courier New", 11, "bold"),
                  fg="#000", bg="#30d158", relief=tk.FLAT, padx=15, pady=8,
                  command=self._export_csv_now).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="🔄  REFRESH PREVIEW",
                  font=("Courier New", 11, "bold"),
                  fg="#000", bg="#00d4ff", relief=tk.FLAT, padx=15, pady=8,
                  command=self._refresh_csv_preview).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="🗑  CLEAR FILE",
                  font=("Courier New", 11, "bold"),
                  fg="#fff", bg="#ff2d55", relief=tk.FLAT, padx=15, pady=8,
                  command=self._clear_csv_file).pack(side=tk.LEFT, padx=10)

        self.csv_info_label = tk.Label(self.tab_csv,
                                        text=f"📁 File: {CSV_FILENAME}  |  Rows: loading...",
                                        font=("Courier New", 10),
                                        fg="#ffd60a", bg="#0a0a0f")
        self.csv_info_label.pack(pady=5)

        tk.Label(self.tab_csv, text="FILE PREVIEW (last 20 rows):",
                 font=("Courier New", 10, "bold"),
                 fg="#555", bg="#0a0a0f").pack(anchor=tk.W, padx=20)

        self.csv_preview = tk.Text(self.tab_csv, bg="#050508", fg="#30d158",
                                   font=("Courier New", 9),
                                   relief=tk.FLAT, padx=10, pady=10)
        self.csv_preview.pack(fill=tk.BOTH, expand=True, padx=20, pady=(2, 15))
        self.csv_preview.insert(tk.END, "Click 'REFRESH PREVIEW' to see the CSV content...\n")

        self._auto_refresh_csv()

    def _export_csv_now(self):
        with stock_lock:
            snapshot = {
                s: {"name": d["name"], "price": d["price"], "history": list(d["history"])}
                for s, d in STOCKS.items()
            }
        with csv_lock:
            with open(CSV_FILENAME, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for symbol, data in snapshot.items():
                    history = data["history"]
                    if len(history) >= 2:
                        prev_price = history[-2][1]
                        change     = round(data["price"] - prev_price, 4)
                        change_pct = round((change / prev_price) * 100, 4)
                    else:
                        change = change_pct = 0.0
                    writer.writerow([ts, symbol, data["name"], data["price"], change, change_pct])
        log_queue.put(("INFO", "Manual CSV export completed."))
        self._refresh_csv_preview()
        messagebox.showinfo("Export Successful", f"Data saved to '{CSV_FILENAME}' ✅")

    def _refresh_csv_preview(self):
        self.csv_preview.config(state=tk.NORMAL)
        self.csv_preview.delete("1.0", tk.END)

        if not os.path.exists(CSV_FILENAME):
            self.csv_preview.insert(tk.END, "File not found yet. Waiting for first save...\n")
            self.csv_info_label.config(text=f"📁 File: {CSV_FILENAME}  |  Rows: 0")
            self.csv_preview.config(state=tk.DISABLED)
            return

        with csv_lock:
            with open(CSV_FILENAME, "r", encoding="utf-8") as f:
                lines = f.readlines()

        total_rows = max(0, len(lines) - 1)
        self.csv_info_label.config(
            text=f"📁 File: {CSV_FILENAME}  |  Total Rows: {total_rows}  |  Size: {os.path.getsize(CSV_FILENAME)} bytes"
        )
        preview_lines = ([lines[0]] + lines[-20:]) if len(lines) > 1 else lines
        self.csv_preview.insert(tk.END, "".join(preview_lines))
        self.csv_preview.see(tk.END)
        self.csv_preview.config(state=tk.DISABLED)

    def _clear_csv_file(self):
        if messagebox.askyesno("Clear CSV", "Are you sure you want to clear the CSV file?"):
            with csv_lock:
                with open(CSV_FILENAME, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(CSV_HEADERS)
            log_queue.put(("INFO", "CSV file cleared."))
            self._refresh_csv_preview()

    def _auto_refresh_csv(self):
        self._refresh_csv_preview()
        self.root.after(15000, self._auto_refresh_csv)

    # ── THREAD MANAGEMENT ──────────────────────────────────────
    def _start_threads(self):
        self.stop_event.clear()
        self.updater_thread   = StockUpdaterThread(self._on_prices_updated, self.stop_event)
        self.alert_thread     = AlertCheckerThread(self._add_alert, self.stop_event)
        self.portfolio_thread = PortfolioThread(self._update_portfolio_ui, self.stop_event)
        self.csv_thread       = CSVLoggerThread(self.stop_event, interval=10)

        self.updater_thread.start()
        self.alert_thread.start()
        self.portfolio_thread.start()
        self.csv_thread.start()

        self.threads_running = True
        self.thread_status.config(text="● THREADS: RUNNING", fg="#30d158")
        for dot in self.thread_indicators.values():
            dot.config(fg="#30d158")

    # ── CALLBACKS / UI UPDATES ─────────────────────────────────
    def _on_prices_updated(self):
        with stock_lock:
            snapshot = {s: {"price": d["price"], "history": list(d["history"])}
                        for s, d in STOCKS.items()}

        for symbol, card in self.stock_cards.items():
            price      = snapshot[symbol]["price"]
            prev       = card.prev_price if hasattr(card, "prev_price") else price
            change     = price - prev
            change_pct = (change / prev * 100) if prev else 0
            arrow      = "▲" if change >= 0 else "▼"
            color      = "#30d158" if change >= 0 else "#ff2d55"

            card.price_label.config(text=f"${price:.2f}", fg="#fff")
            card.change_label.config(
                text=f"{arrow} {abs(change):.2f}  ({change_pct:+.2f}%)", fg=color)
            card.prev_price = price

        all_prices = [(s, snapshot[s]["price"]) for s in STOCKS]
        total      = sum(p for _, p in all_prices)
        self.market_summary.config(
            text=f"Tracking {len(STOCKS)} stocks  |  "
                 f"Total mkt cap proxy: ${total:,.2f}  |  "
                 f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    def _poll_logs(self):
        try:
            while True:
                level, msg = log_queue.get_nowait()
                ts    = datetime.now().strftime("%H:%M:%S")
                color = {"INFO": "#00d4ff", "ALERT": "#ff2d55", "WARN": "#ffd60a"}.get(level, "#aaa")
                self.console.insert(tk.END, f"[{ts}] [{level:5s}] {msg}\n")
                self.console.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(300, self._poll_logs)

    def _update_clock(self):
        self.clock_label.config(text=datetime.now().strftime("%A  %H:%M:%S"))
        self.root.after(1000, self._update_clock)

    def on_close(self):
        self.stop_event.set()
        self.root.destroy()


# ═══════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app  = StockMonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
