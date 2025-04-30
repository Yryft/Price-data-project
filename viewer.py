import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from datetime import datetime

import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

DB_FILE = "prices.db"

# ── Autocomplete Combobox ────────────────────────────────────────────────────
class AutocompleteCombobox(ttk.Combobox):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._completion_list = []
        self._after_id = None
        self.bind('<KeyRelease>', self._on_keyrelease)

    def set_completion_list(self, completion_list):
        self._completion_list = sorted(completion_list, key=str.lower)
        self['values'] = self._completion_list

    def _on_keyrelease(self, event):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(1000, self._filter_list)  # 1 second bounce

    def _filter_list(self):
        text = self.get()
        data = self._completion_list if not text else [item for item in self._completion_list if text.lower() in item.lower()]
        self['values'] = data
        if data:
            self.event_generate('<Down>')

# ── Main Application ───────────────────────────────────────────────────────────
class PriceViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Price Data Viewer")
        self.conn = sqlite3.connect(DB_FILE)

        # Layout configuration
        root.grid_columnconfigure(0, weight=3)
        root.grid_columnconfigure(1, weight=2)
        root.grid_columnconfigure(2, weight=1)
        root.grid_rowconfigure(3, weight=1)
        root.grid_rowconfigure(4, weight=0)

        # Controls
        ttk.Label(root, text="Select Table:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.table_var = tk.StringVar()
        self.table_combo = ttk.Combobox(root, textvariable=self.table_var, state="readonly",
                                        values=["auction_prices", "bazaar_prices"])
        self.table_combo.current(0)
        self.table_combo.grid(row=0, column=1, padx=5, pady=5)
        self.table_combo.bind("<<ComboboxSelected>>", self.update_item_list)

        ttk.Label(root, text="Select Item:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.item_var = tk.StringVar()
        self.item_combo = AutocompleteCombobox(root, textvariable=self.item_var, width=50)
        self.item_combo.grid(row=1, column=1, padx=5, pady=5)

        ttk.Button(root, text="OK", command=self.show_entries).grid(row=2, column=0, columnspan=2, pady=10)

        # Data table
        self.tree = ttk.Treeview(root, show="headings")
        self.tree.grid(row=3, column=0, sticky="nsew", padx=(5,0), pady=5)
        vsb = ttk.Scrollbar(root, orient="vertical", command=self.tree.yview)
        vsb.grid(row=3, column=0, sticky='nse', padx=(0,5), pady=5)
        self.tree.configure(yscrollcommand=vsb.set)

        # Analysis text
        self.analysis_text = tk.Text(root, height=5, wrap="word", state="disabled", background="#f0f0f0")
        self.analysis_text.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

        # Graph frame with toggle
        self.graph_frame = ttk.Labelframe(root, text="Price Graph")
        self.graph_frame.grid(row=3, column=1, rowspan=2, columnspan=2, sticky="nsew", padx=5, pady=5)
        self.graph_visible = True
        self.toggle_btn = ttk.Button(root, text="Hide Graph", command=self.toggle_graph)
        self.toggle_btn.grid(row=2, column=2)

        # Matplotlib canvas inside graph_frame
        self.fig = Figure(figsize=(4,3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.update_item_list()
        self.show_global_movers()

    def toggle_graph(self):
        if self.graph_visible:
            self.graph_frame.grid_remove()
            self.toggle_btn.config(text="Show Graph")
        else:
            self.graph_frame.grid()
            self.toggle_btn.config(text="Hide Graph")
        self.graph_visible = not self.graph_visible

    def update_item_list(self, event=None):
        cur = self.conn.cursor()
        if self.table_var.get() == "auction_prices":
            cur.execute("SELECT DISTINCT item_id FROM auction_prices ORDER BY item_id")
            items = [r[0] for r in cur.fetchall()]
        else:
            cur.execute("SELECT DISTINCT product_id FROM bazaar_prices ORDER BY product_id")
            items = [r[0] for r in cur.fetchall()]
        self.item_combo.set_completion_list(items)
        self.item_combo.delete(0, tk.END)

    def show_entries(self):
        table = self.table_var.get()
        item = self.item_var.get().strip()
        if not item:
            messagebox.showwarning("Input needed", "Please select or type an item.")
            return

        cur = self.conn.cursor()
        # Clear previous
        for row in self.tree.get_children(): self.tree.delete(row)

        times, prices = [], []
        if table == "auction_prices":
            cols = ("id","timestamp","item_id","price")
            cur.execute("SELECT id,timestamp,item_id,price FROM auction_prices WHERE item_id=? ORDER BY timestamp", (item,))
            rows = cur.fetchall()
            for r in rows:
                times.append(datetime.fromtimestamp(r[1]))
                prices.append(r[3])
        else:
            cols = ("id","timestamp","product_id","buy_price")
            cur.execute("SELECT id,timestamp,product_id,buy_price FROM bazaar_prices WHERE product_id=? ORDER BY timestamp", (item,))
            rows = cur.fetchall()
            for r in rows:
                times.append(datetime.fromtimestamp(r[1]))
                prices.append(r[3])

        self.tree.configure(columns=cols)
        for c in cols: self.tree.heading(c, text=c)
        for r in rows: self.tree.insert("","end",values=r)

        # Update graph
        self.ax.clear()
        if times and prices:
            self.ax.plot(times, prices, marker='o')
            self.ax.set_title(f"{table} history for {item}")
            self.ax.set_xlabel("Time")
            self.ax.set_ylabel("Price")
            self.fig.autofmt_xdate()
        self.canvas.draw()

        # Update analysis text
        if prices:
            mn, mx = min(prices), max(prices)
            avg = sum(prices)/len(prices)
            change = prices[-1] - prices[0]
            pct = (change/prices[0]*100) if prices[0] else 0
            lines=[f"Min: {mn:.2f}",f"Max: {mx:.2f}",f"Avg: {avg:.2f}",f"Δ: {change:+.2f}",f"%: {pct:+.2f}%"]
        else:
            lines=["No data"]
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete(1.0, tk.END)
        self.analysis_text.insert(tk.END, " | ".join(lines))
        self.analysis_text.configure(state="disabled")

    def show_global_movers(self):
        c=self.conn.cursor(); result=["Top Movers - last 2h"]
        # Auction
        c.execute("SELECT item_id,price,timestamp FROM auction_prices WHERE timestamp>=strftime('%s','now','-2 hours') ORDER BY timestamp DESC")
        rows=c.fetchall(); latest={}
        for i,p,ts in rows: latest.setdefault(i,p)
        spikes=[]
        for i,p in latest.items():
            c.execute("SELECT price FROM auction_prices WHERE item_id=? ORDER BY timestamp DESC LIMIT 100 OFFSET 1",(i,))
            old=c.fetchall()
            if old:
                avg_old=sum(x[0] for x in old)/len(old)
                spikes.append((f"A-{i}",(p-avg_old)/avg_old*100))
        # Bazaar
        c.execute("SELECT product_id,buy_price,sell_price,timestamp FROM bazaar_prices WHERE timestamp>=strftime('%s','now','-2 hours') ORDER BY timestamp DESC")
        rows=c.fetchall(); latest={}
        for prod,b,s,ts in rows: latest.setdefault(prod,(b+s)/2)
        for prod,p in latest.items():
            c.execute("SELECT buy_price,sell_price FROM bazaar_prices WHERE product_id=? ORDER BY timestamp DESC LIMIT 100 OFFSET 1",(prod,))
            old=c.fetchall()
            if old:
                avg_old=sum((x[0]+x[1])/2 for x in old)/len(old)
                try:
                    spikes.append((f"B-{prod}",(p-avg_old)/avg_old*100))
                except ZeroDivisionError: pass
        spikes.sort(key=lambda x:abs(x[1]),reverse=True)
        for itm,ch in spikes[:20]: result.append(f"{itm}:{ch:+.2f}%")
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete(1.0,tk.END)
        self.analysis_text.insert(tk.END,"\n".join(result))
        self.analysis_text.configure(state="disabled")

# ── Entry Point ─────────────────────────────────────────────────────────
if __name__=="__main__":
    root=tk.Tk()
    PriceViewerApp(root)
    root.mainloop()
