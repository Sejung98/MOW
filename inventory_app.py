"""Inventory, sales, tax, and financial reporting application.

The application uses SQLite for persistence and Tkinter for a simple GUI.
It supports managing products, logging sales and inventory movements, and
automatically generates tax documents and financial statements.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "mow.db"


def _dict_factory(cursor: sqlite3.Cursor, row: Tuple) -> Dict:
    """Return a dict row for SQLite queries."""

    return {col[0]: value for col, value in zip(cursor.description, row)}


class DatabaseManager:
    """High level access to the SQLite database."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = _dict_factory
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    cost REAL NOT NULL,
                    price REAL NOT NULL,
                    stock INTEGER NOT NULL DEFAULT 0,
                    reorder_level INTEGER NOT NULL DEFAULT 0
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    movement_type TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_cost REAL NOT NULL,
                    movement_date TEXT NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    sale_price REAL NOT NULL,
                    sale_date TEXT NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cash_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    movement_type TEXT NOT NULL,
                    movement_date TEXT NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tax_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    vat_rate REAL NOT NULL,
                    income_tax_rate REAL NOT NULL
                )
                """
            )

            cur.execute(
                """
                INSERT INTO tax_settings(id, vat_rate, income_tax_rate)
                VALUES (1, 0.10, 0.10)
                ON CONFLICT(id) DO NOTHING
                """
            )
            conn.commit()

    # Product operations -------------------------------------------------
    def add_product(
        self,
        product_code: str,
        name: str,
        cost: float,
        price: float,
        stock: int,
        reorder_level: int,
    ) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO products
                (product_code, name, cost, price, stock, reorder_level)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (product_code, name, cost, price, stock, reorder_level),
            )
            product_id = cur.lastrowid
            if stock:
                self._log_inventory_movement(cur, product_id, "IN", stock, cost)
            conn.commit()

    def restock(self, product_code: str, quantity: int) -> None:
        product = self.get_product(product_code)
        if not product:
            raise ValueError("Product not found")
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE products SET stock = stock + ? WHERE product_code = ?",
                (quantity, product_code),
            )
            self._log_inventory_movement(cur, product["id"], "IN", quantity, product["cost"])
            self._log_cash(cur, f"Purchase of {product['name']}", -(product["cost"] * quantity))
            conn.commit()

    def get_product(self, product_code: str) -> Optional[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM products WHERE product_code = ?", (product_code,))
            return cur.fetchone()

    def fetch_products(self) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM products ORDER BY name")
            return cur.fetchall() or []

    def get_low_stock(self) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM products WHERE stock <= reorder_level ORDER BY name"
            )
            return cur.fetchall() or []

    # Sales ---------------------------------------------------------------
    def record_sale(self, product_code: str, quantity: int) -> Dict:
        product = self.get_product(product_code)
        if not product:
            raise ValueError("Product not found")
        if product["stock"] < quantity:
            raise ValueError("Insufficient stock")
        sale_price = product["price"]
        cost = product["cost"]
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (quantity, product["id"]),
            )
            cur.execute(
                """
                INSERT INTO sales(product_id, quantity, sale_price, sale_date)
                VALUES (?, ?, ?, ?)
                """,
                (
                    product["id"],
                    quantity,
                    sale_price,
                    dt.date.today().isoformat(),
                ),
            )
            self._log_inventory_movement(cur, product["id"], "OUT", quantity, cost)
            self._log_cash(cur, f"Sale of {product['name']}", sale_price * quantity)
            conn.commit()
        return {
            "product": product,
            "quantity": quantity,
            "sale_price": sale_price,
            "revenue": sale_price * quantity,
            "cogs": cost * quantity,
        }

    def fetch_sales(self, limit: int = 50) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT s.id, p.product_code, p.name, s.quantity, s.sale_price, s.sale_date
                FROM sales s
                JOIN products p ON p.id = s.product_id
                ORDER BY s.sale_date DESC, s.id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return cur.fetchall() or []

    # Financial helpers --------------------------------------------------
    def get_tax_rates(self) -> Dict[str, float]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT vat_rate, income_tax_rate FROM tax_settings WHERE id = 1")
            return cur.fetchone()

    def update_tax_rates(self, vat_rate: float, income_tax_rate: float) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tax_settings SET vat_rate = ?, income_tax_rate = ? WHERE id = 1",
                (vat_rate, income_tax_rate),
            )
            conn.commit()

    def get_monthly_summary(self, year: int, month: int) -> Dict[str, float]:
        start = dt.date(year, month, 1)
        if month == 12:
            end = dt.date(year + 1, 1, 1)
        else:
            end = dt.date(year, month + 1, 1)

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT SUM(quantity * sale_price) AS revenue,
                       SUM(quantity * p.cost) AS cogs
                FROM sales s
                JOIN products p ON p.id = s.product_id
                WHERE s.sale_date >= ? AND s.sale_date < ?
                """,
                (start.isoformat(), end.isoformat()),
            )
            row = cur.fetchone() or {}
            revenue = row.get("revenue") or 0.0
            cogs = row.get("cogs") or 0.0

            cur.execute(
                """
                SELECT SUM(quantity * unit_cost) AS purchases
                FROM inventory_movements
                WHERE movement_type = 'IN'
                AND movement_date >= ? AND movement_date < ?
                """,
                (start.isoformat(), end.isoformat()),
            )
            purchases = (cur.fetchone() or {}).get("purchases") or 0.0

            cur.execute(
                """
                SELECT SUM(amount) AS cash_flow
                FROM cash_movements
                WHERE movement_date >= ? AND movement_date < ?
                """,
                (start.isoformat(), end.isoformat()),
            )
            cash_flow = (cur.fetchone() or {}).get("cash_flow") or 0.0

        tax_rates = self.get_tax_rates()
        gross_profit = revenue - cogs
        vat = revenue * tax_rates["vat_rate"]
        income_tax = max(gross_profit, 0) * tax_rates["income_tax_rate"]
        net_income = gross_profit - income_tax

        inventory_value = self.get_inventory_value()
        cash_balance = self.get_cash_balance()

        return {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "vat": vat,
            "income_tax": income_tax,
            "net_income": net_income,
            "purchases": purchases,
            "cash_flow": cash_flow,
            "inventory_value": inventory_value,
            "cash_balance": cash_balance,
            "assets": cash_balance + inventory_value,
            "liabilities": vat + income_tax,
            "equity": cash_balance + inventory_value - (vat + income_tax),
        }

    def get_inventory_value(self) -> float:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT SUM(stock * cost) AS value FROM products")
            return (cur.fetchone() or {}).get("value") or 0.0

    def get_cash_balance(self) -> float:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT SUM(amount) AS balance FROM cash_movements")
            return (cur.fetchone() or {}).get("balance") or 0.0

    # logging -------------------------------------------------------------
    def _log_inventory_movement(
        self,
        cur: sqlite3.Cursor,
        product_id: int,
        movement_type: str,
        quantity: int,
        unit_cost: float,
    ) -> None:
        cur.execute(
            """
            INSERT INTO inventory_movements
            (product_id, movement_type, quantity, unit_cost, movement_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (product_id, movement_type, quantity, unit_cost, dt.date.today().isoformat()),
        )

    def _log_cash(self, cur: sqlite3.Cursor, description: str, amount: float) -> None:
        cur.execute(
            """
            INSERT INTO cash_movements(description, amount, movement_type, movement_date)
            VALUES (?, ?, ?, ?)
            """,
            (
                description,
                amount,
                "IN" if amount >= 0 else "OUT",
                dt.date.today().isoformat(),
            ),
        )

    # Backup --------------------------------------------------------------
    def backup(self, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.db_path, destination)
        return destination

    def restore(self, source: Path) -> None:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(source)
        shutil.copy2(source, self.db_path)


class ReportGenerator:
    """Generate structured financial reports using pandas."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def build_profit_and_loss(self, year: int, month: int) -> pd.DataFrame:
        summary = self.db.get_monthly_summary(year, month)
        data = {
            "Metric": [
                "Revenue",
                "Cost of Goods Sold",
                "Gross Profit",
                "Income Tax",
                "Net Income",
            ],
            "Amount": [
                summary["revenue"],
                summary["cogs"],
                summary["gross_profit"],
                summary["income_tax"],
                summary["net_income"],
            ],
        }
        return pd.DataFrame(data)

    def build_balance_sheet(self, year: int, month: int) -> pd.DataFrame:
        summary = self.db.get_monthly_summary(year, month)
        data = {
            "Category": ["Assets", "Liabilities", "Equity"],
            "Amount": [summary["assets"], summary["liabilities"], summary["equity"]],
        }
        return pd.DataFrame(data)

    def build_cash_flow(self, year: int, month: int) -> pd.DataFrame:
        summary = self.db.get_monthly_summary(year, month)
        data = {
            "Category": ["Operating Cash Flow", "Purchases", "Net Cash"],
            "Amount": [summary["cash_flow"], -summary["purchases"], summary["cash_flow"] - summary["purchases"]],
        }
        return pd.DataFrame(data)

    def export_monthly_reports(self, year: int, month: int, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(output_path) as writer:
            self.build_profit_and_loss(year, month).to_excel(writer, sheet_name="P&L", index=False)
            self.build_balance_sheet(year, month).to_excel(writer, sheet_name="Balance", index=False)
            self.build_cash_flow(year, month).to_excel(writer, sheet_name="CashFlow", index=False)


@dataclass
class TaxInvoice:
    product_code: str
    product_name: str
    quantity: int
    unit_price: float
    vat_rate: float

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price

    @property
    def vat(self) -> float:
        return self.subtotal * self.vat_rate

    @property
    def total(self) -> float:
        return self.subtotal + self.vat

    def to_row(self) -> List:
        return [self.product_code, self.product_name, self.quantity, self.unit_price, self.subtotal, self.vat, self.total]


class InventoryApp:
    """Tkinter user interface."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("MOW Inventory & Finance")
        master.geometry("1024x720")
        self.db = DatabaseManager()
        self.reporter = ReportGenerator(self.db)

        self.notebook = ttk.Notebook(master)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_inventory_tab()
        self._build_sales_tab()
        self._build_reports_tab()
        self._build_tax_tab()
        self._build_backup_tab()
        self.refresh_products()
        self.refresh_sales()

    # Inventory tab ------------------------------------------------------
    def _build_inventory_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Inventory")

        form = ttk.LabelFrame(frame, text="Add / Update Product")
        form.pack(fill=tk.X, padx=10, pady=10)

        self.product_code = tk.StringVar()
        self.product_name = tk.StringVar()
        self.product_cost = tk.DoubleVar(value=0.0)
        self.product_price = tk.DoubleVar(value=0.0)
        self.product_stock = tk.IntVar(value=0)
        self.product_reorder = tk.IntVar(value=5)

        self._add_labeled_entry(form, "Code", self.product_code, 0)
        self._add_labeled_entry(form, "Name", self.product_name, 1)
        self._add_labeled_entry(form, "Cost", self.product_cost, 2)
        self._add_labeled_entry(form, "Price", self.product_price, 3)
        self._add_labeled_entry(form, "Initial Stock", self.product_stock, 4)
        self._add_labeled_entry(form, "Reorder Level", self.product_reorder, 5)

        ttk.Button(form, text="Save Product", command=self.save_product).grid(row=0, column=6, rowspan=2, padx=10)
        ttk.Button(form, text="Restock", command=self.prompt_restock).grid(row=2, column=6, rowspan=2, padx=10)

        self.products_tree = ttk.Treeview(frame, columns=("code", "name", "cost", "price", "stock", "reorder"), show="headings")
        for col in ("code", "name", "cost", "price", "stock", "reorder"):
            self.products_tree.heading(col, text=col.title())
        self.products_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.low_stock_label = ttk.Label(frame, text="Low stock items will appear here.")
        self.low_stock_label.pack(padx=10, pady=5)

    def _add_labeled_entry(self, parent, text, variable, row):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(parent, textvariable=variable, width=15).grid(row=row, column=1, padx=5, pady=5)

    def save_product(self) -> None:
        try:
            self.db.add_product(
                self.product_code.get(),
                self.product_name.get(),
                float(self.product_cost.get()),
                float(self.product_price.get()),
                int(self.product_stock.get()),
                int(self.product_reorder.get()),
            )
            messagebox.showinfo("Product", "Product saved")
            self.refresh_products()
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("Error", str(exc))

    def prompt_restock(self) -> None:
        code = self.product_code.get()
        qty = tk.simpledialog.askinteger("Restock", "Quantity", minvalue=1)
        if not qty:
            return
        try:
            self.db.restock(code, qty)
            messagebox.showinfo("Restock", "Inventory updated")
            self.refresh_products()
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("Error", str(exc))

    def refresh_products(self) -> None:
        for item in self.products_tree.get_children():
            self.products_tree.delete(item)
        for product in self.db.fetch_products():
            self.products_tree.insert(
                "",
                tk.END,
                values=(
                    product["product_code"],
                    product["name"],
                    f"{product['cost']:.2f}",
                    f"{product['price']:.2f}",
                    product["stock"],
                    product["reorder_level"],
                ),
            )
        low = self.db.get_low_stock()
        if low:
            summary = ", ".join(f"{p['name']} ({p['stock']})" for p in low)
            self.low_stock_label.config(text=f"Low stock: {summary}")
        else:
            self.low_stock_label.config(text="All inventory levels are healthy.")

    # Sales tab ----------------------------------------------------------
    def _build_sales_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Sales")

        form = ttk.LabelFrame(frame, text="Record Sale")
        form.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(form, text="Product").grid(row=0, column=0, padx=5, pady=5)
        self.sale_product = tk.StringVar()
        self.sale_product_combo = ttk.Combobox(form, textvariable=self.sale_product, state="readonly")
        self.sale_product_combo.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(form, text="Quantity").grid(row=0, column=2, padx=5, pady=5)
        self.sale_qty = tk.IntVar(value=1)
        ttk.Entry(form, textvariable=self.sale_qty, width=10).grid(row=0, column=3, padx=5, pady=5)

        ttk.Button(form, text="Add Sale", command=self.record_sale).grid(row=0, column=4, padx=5, pady=5)

        self.sales_tree = ttk.Treeview(frame, columns=("date", "product", "qty", "price"), show="headings")
        for col in ("date", "product", "qty", "price"):
            self.sales_tree.heading(col, text=col.title())
        self.sales_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def record_sale(self) -> None:
        code = self.sale_product.get()
        qty = int(self.sale_qty.get())
        try:
            sale = self.db.record_sale(code, qty)
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("Sale", str(exc))
            return
        invoice = TaxInvoice(
            product_code=code,
            product_name=sale["product"]["name"],
            quantity=qty,
            unit_price=sale["sale_price"],
            vat_rate=self.db.get_tax_rates()["vat_rate"],
        )
        self.save_invoice(invoice)
        messagebox.showinfo(
            "Sale",
            f"Revenue: {sale['revenue']:.2f}\nCOGS: {sale['cogs']:.2f}\nInvoice saved.",
        )
        self.refresh_products()
        self.refresh_sales()

    def save_invoice(self, invoice: TaxInvoice) -> None:
        invoices_dir = DATA_DIR / "invoices"
        invoices_dir.mkdir(parents=True, exist_ok=True)
        filename = invoices_dir / f"invoice_{invoice.product_code}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(["Product Code", "Product", "Quantity", "Unit Price", "Subtotal", "VAT", "Total"])
            writer.writerow(invoice.to_row())

    def refresh_sales(self) -> None:
        for item in self.sales_tree.get_children():
            self.sales_tree.delete(item)
        products = {p["product_code"]: p for p in self.db.fetch_products()}
        for sale in self.db.fetch_sales():
            self.sales_tree.insert(
                "",
                tk.END,
                values=(sale["sale_date"], sale["name"], sale["quantity"], f"{sale['sale_price']:.2f}"),
            )
        codes = list(products.keys())
        self.sale_product_combo["values"] = codes
        if codes and not self.sale_product.get():
            self.sale_product.set(codes[0])

    # Reports tab --------------------------------------------------------
    def _build_reports_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Reports")

        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, padx=10, pady=10)

        current = dt.date.today()
        self.report_year = tk.IntVar(value=current.year)
        self.report_month = tk.IntVar(value=current.month)

        ttk.Label(controls, text="Year").grid(row=0, column=0, padx=5)
        ttk.Entry(controls, textvariable=self.report_year, width=6).grid(row=0, column=1, padx=5)
        ttk.Label(controls, text="Month").grid(row=0, column=2, padx=5)
        ttk.Entry(controls, textvariable=self.report_month, width=4).grid(row=0, column=3, padx=5)
        ttk.Button(controls, text="Generate", command=self.display_report).grid(row=0, column=4, padx=5)
        ttk.Button(controls, text="Export Excel", command=self.export_reports).grid(row=0, column=5, padx=5)

        self.report_text = tk.Text(frame, height=20)
        self.report_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def display_report(self) -> None:
        summary = self.db.get_monthly_summary(self.report_year.get(), self.report_month.get())
        lines = ["Monthly Financial Summary"]
        for key, label in [
            ("revenue", "Revenue"),
            ("cogs", "Cost of Goods Sold"),
            ("gross_profit", "Gross Profit"),
            ("income_tax", "Income Tax"),
            ("net_income", "Net Income"),
            ("cash_flow", "Operating Cash Flow"),
            ("inventory_value", "Inventory Value"),
            ("cash_balance", "Cash Balance"),
        ]:
            lines.append(f"{label}: {summary[key]:,.2f}")
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, "\n".join(lines))

    def export_reports(self) -> None:
        year = self.report_year.get()
        month = self.report_month.get()
        file_path = filedialog.asksaveasfilename(
            title="Save Reports", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")]
        )
        if not file_path:
            return
        self.reporter.export_monthly_reports(year, month, Path(file_path))
        messagebox.showinfo("Reports", "Exported successfully")

    # Tax tab ------------------------------------------------------------
    def _build_tax_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Taxes")

        rates = self.db.get_tax_rates()
        self.vat_rate = tk.DoubleVar(value=rates["vat_rate"])
        self.income_tax_rate = tk.DoubleVar(value=rates["income_tax_rate"])

        ttk.Label(frame, text="VAT Rate").grid(row=0, column=0, padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.vat_rate).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(frame, text="Income Tax Rate").grid(row=1, column=0, padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.income_tax_rate).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(frame, text="Update", command=self.save_tax_rates).grid(row=2, column=0, columnspan=2, pady=10)

    def save_tax_rates(self) -> None:
        try:
            self.db.update_tax_rates(float(self.vat_rate.get()), float(self.income_tax_rate.get()))
            messagebox.showinfo("Tax", "Rates updated")
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("Tax", str(exc))

    # Backup tab ---------------------------------------------------------
    def _build_backup_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Backup")

        ttk.Button(frame, text="Create Backup", command=self.create_backup).pack(padx=10, pady=10)
        ttk.Button(frame, text="Restore Backup", command=self.restore_backup).pack(padx=10, pady=10)

    def create_backup(self) -> None:
        backup_path = filedialog.asksaveasfilename(
            title="Backup Database",
            defaultextension=".db",
            initialfile=f"backup_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
        )
        if not backup_path:
            return
        self.db.backup(Path(backup_path))
        messagebox.showinfo("Backup", "Backup completed")

    def restore_backup(self) -> None:
        source = filedialog.askopenfilename(title="Select Backup", filetypes=[("DB", "*.db")])
        if not source:
            return
        self.db.restore(Path(source))
        messagebox.showinfo("Backup", "Database restored")
        self.refresh_products()
        self.refresh_sales()


def main() -> None:
    root = tk.Tk()
    InventoryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
