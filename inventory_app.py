"""재고, 매출, 세금, 재무 보고를 한 번에 처리하는 데스크톱 애플리케이션."""

from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from tkinter import filedialog, messagebox, simpledialog, ttk


APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "mow.db"
THEME_PATH = APP_DIR / "theme.json"
SYNC_DIR = APP_DIR / "sync"
EXCEL_SYNC_PATH = SYNC_DIR / "mow_sync.xlsx"
TSV_SYNC_PATH = SYNC_DIR / "mow_sync.tsv"


@dataclass
class ThemeConfig:
    """UI 구성을 JSON 파일에서 불러오기 위한 데이터 클래스."""

    font_family: str = "맑은 고딕"
    font_size: int = 11
    background: str = "#f4f5f7"
    surface: str = "#ffffff"
    accent: str = "#2563eb"
    accent_text: str = "#ffffff"
    border_color: str = "#d1d5db"
    text_color: str = "#111827"
    tree_stripe: str = "#f8fafc"


class ThemeManager:
    """theme.json을 읽어 Tkinter 스타일을 동적으로 지정한다."""

    def __init__(self, master: tk.Tk, config_path: Path = THEME_PATH) -> None:
        self.master = master
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.apply()

    def _load_config(self) -> ThemeConfig:
        defaults = ThemeConfig()
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                merged = asdict(defaults)
                merged.update(data)
                return ThemeConfig(**merged)
            except (json.JSONDecodeError, TypeError):  # 잘못된 설정은 기본값 사용
                pass
        self._save(defaults)
        return defaults

    def _save(self, config: ThemeConfig) -> None:
        self.config_path.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def apply(self) -> None:
        cfg = self.config
        base_font = (cfg.font_family, cfg.font_size)
        self.master.option_add("*Font", base_font)
        self.master.configure(background=cfg.background)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=cfg.background)
        style.configure("TLabelframe", background=cfg.surface, relief="flat", borderwidth=1)
        style.configure("TLabelframe.Label", background=cfg.surface, foreground=cfg.text_color)
        style.configure("TLabel", background=cfg.background, foreground=cfg.text_color)
        style.configure(
            "TNotebook",
            background=cfg.background,
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            padding=(16, 8),
            background=cfg.surface,
            foreground=cfg.text_color,
        )
        style.map("TNotebook.Tab", background=[("selected", cfg.accent)], foreground=[("selected", cfg.accent_text)])
        style.configure(
            "TButton",
            padding=(10, 6),
            background=cfg.surface,
            foreground=cfg.text_color,
        )
        style.map(
            "TButton",
            background=[("active", cfg.accent)],
            foreground=[("active", cfg.accent_text)],
        )
        style.configure(
            "Treeview",
            background=cfg.surface,
            fieldbackground=cfg.surface,
            foreground=cfg.text_color,
            rowheight=26,
        )
        style.map(
            "Treeview",
            background=[("selected", cfg.accent)],
            foreground=[("selected", cfg.accent_text)],
        )


def _dict_factory(cursor: sqlite3.Cursor, row: Tuple) -> Dict:
    """SQLite 조회 결과를 dict로 반환한다."""

    return {col[0]: value for col, value in zip(cursor.description, row)}


class DatabaseManager:
    """SQLite 데이터베이스에 대한 고수준 접근 레이어."""

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
            raise ValueError("해당 상품을 찾을 수 없습니다.")
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE products SET stock = stock + ? WHERE product_code = ?",
                (quantity, product_code),
            )
            self._log_inventory_movement(cur, product["id"], "IN", quantity, product["cost"])
            self._log_cash(cur, f"{product['name']} 매입", -(product["cost"] * quantity))
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
            raise ValueError("해당 상품을 찾을 수 없습니다.")
        if product["stock"] < quantity:
            raise ValueError("재고가 부족합니다.")
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
            self._log_cash(cur, f"{product['name']} 판매 수익", sale_price * quantity)
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

    def fetch_all_sales(self) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT s.id, p.product_code, p.name, s.quantity, s.sale_price, s.sale_date
                FROM sales s
                JOIN products p ON p.id = s.product_id
                ORDER BY s.sale_date ASC, s.id ASC
                """
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

    def get_monthly_trends(self, months: int = 12) -> List[Dict]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT substr(s.sale_date, 1, 7) AS period,
                       SUM(s.quantity * s.sale_price) AS revenue,
                       SUM(s.quantity * p.cost) AS cogs
                FROM sales s
                JOIN products p ON p.id = s.product_id
                GROUP BY period
                ORDER BY period DESC
                LIMIT ?
                """,
                (months,),
            )
            rows = cur.fetchall() or []
        rates = self.get_tax_rates()
        trend: List[Dict] = []
        for row in reversed(rows):
            revenue = row.get("revenue") or 0.0
            cogs = row.get("cogs") or 0.0
            gross = revenue - cogs
            trend.append(
                {
                    "period": row.get("period"),
                    "revenue": revenue,
                    "gross_profit": gross,
                    "vat": revenue * rates["vat_rate"],
                    "income_tax": max(gross, 0) * rates["income_tax_rate"],
                }
            )
        return trend

    def bulk_upsert_products(self, rows: List[Dict]) -> None:
        if not rows:
            return
        with self._connect() as conn:
            cur = conn.cursor()
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO products (product_code, name, cost, price, stock, reorder_level)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(product_code) DO UPDATE SET
                        name = excluded.name,
                        cost = excluded.cost,
                        price = excluded.price,
                        stock = excluded.stock,
                        reorder_level = excluded.reorder_level
                    """,
                    (
                        row.get("product_code"),
                        row.get("name"),
                        float(row.get("cost", 0.0)),
                        float(row.get("price", 0.0)),
                        int(row.get("stock", 0)),
                        int(row.get("reorder_level", 0)),
                    ),
                )
            conn.commit()

    def replace_sales(self, rows: List[Dict]) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM sales")
            products = {p["product_code"]: p["id"] for p in self.fetch_products()}
            for row in rows:
                code = row.get("product_code")
                product_id = products.get(code)
                if not product_id:
                    continue
                cur.execute(
                    """
                    INSERT INTO sales (product_id, quantity, sale_price, sale_date)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        product_id,
                        int(row.get("quantity", 0)),
                        float(row.get("sale_price", 0.0)),
                        str(row.get("sale_date") or dt.date.today().isoformat()),
                    ),
                )
            conn.commit()

    def apply_tax_frame(self, data: Dict[str, float]) -> None:
        vat = float(data.get("vat_rate", 0.1))
        income = float(data.get("income_tax_rate", 0.1))
        self.update_tax_rates(vat, income)

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
    """pandas로 손익계산서 등 주요 재무제표를 생성한다."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def build_profit_and_loss(self, year: int, month: int) -> pd.DataFrame:
        summary = self.db.get_monthly_summary(year, month)
        data = {
            "항목": [
                "매출액",
                "매출원가",
                "매출총이익",
                "소득세",
                "당기순이익",
            ],
            "금액": [
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
            "구분": ["자산", "부채", "자본"],
            "금액": [summary["assets"], summary["liabilities"], summary["equity"]],
        }
        return pd.DataFrame(data)

    def build_cash_flow(self, year: int, month: int) -> pd.DataFrame:
        summary = self.db.get_monthly_summary(year, month)
        data = {
            "구분": ["영업현금흐름", "상품 매입", "순현금"],
            "금액": [summary["cash_flow"], -summary["purchases"], summary["cash_flow"] - summary["purchases"]],
        }
        return pd.DataFrame(data)

    def export_monthly_reports(self, year: int, month: int, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(output_path) as writer:
            self.build_profit_and_loss(year, month).to_excel(writer, sheet_name="손익계산서", index=False)
            self.build_balance_sheet(year, month).to_excel(writer, sheet_name="대차대조표", index=False)
            self.build_cash_flow(year, month).to_excel(writer, sheet_name="현금흐름표", index=False)


class SyncManager:
    """엑셀/TSV 문서를 통해 데이터를 양방향 동기화한다."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        SYNC_DIR.mkdir(parents=True, exist_ok=True)

    def export_documents(self) -> Tuple[Path, Path]:
        frames = self._build_frames()
        excel_path = EXCEL_SYNC_PATH
        tsv_path = TSV_SYNC_PATH
        with pd.ExcelWriter(excel_path) as writer:
            for sheet, frame in frames.items():
                frame.to_excel(writer, sheet_name=sheet, index=False)
        with open(tsv_path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp, delimiter="\t")
            writer.writerow(["table", "json"])
            for name, frame in frames.items():
                for row in frame.to_dict("records"):
                    writer.writerow([name, json.dumps(row, ensure_ascii=False)])
        return excel_path, tsv_path

    def import_from_excel(self, path: Optional[Path] = None) -> None:
        target = Path(path) if path else EXCEL_SYNC_PATH
        if not target.exists():
            raise FileNotFoundError(target)
        frames = pd.read_excel(target, sheet_name=None)
        self._apply_frames(frames)

    def import_from_tsv(self, path: Optional[Path] = None) -> None:
        target = Path(path) if path else TSV_SYNC_PATH
        if not target.exists():
            raise FileNotFoundError(target)
        mapping: Dict[str, List[Dict]] = {}
        df = pd.read_csv(target, delimiter="\t")
        for _, row in df.iterrows():
            table = row.get("table")
            payload = row.get("json")
            if not table or not payload:
                continue
            mapping.setdefault(table, []).append(json.loads(payload))
        frames = {name: pd.DataFrame(records) for name, records in mapping.items()}
        self._apply_frames(frames)

    def _build_frames(self) -> Dict[str, pd.DataFrame]:
        frames: Dict[str, pd.DataFrame] = {}
        frames["products"] = pd.DataFrame(self.db.fetch_products())
        frames["sales"] = pd.DataFrame(self.db.fetch_all_sales())
        frames["tax_settings"] = pd.DataFrame([self.db.get_tax_rates()])
        return frames

    def _apply_frames(self, frames: Dict[str, pd.DataFrame]) -> None:
        if "products" in frames:
            self.db.bulk_upsert_products(frames["products"].fillna(0).to_dict("records"))
        if "sales" in frames:
            self.db.replace_sales(frames["sales"].fillna(0).to_dict("records"))
        if "tax_settings" in frames and not frames["tax_settings"].empty:
            self.db.apply_tax_frame(frames["tax_settings"].iloc[0].to_dict())
        self.export_documents()


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
    """한글 기반 Tkinter 사용자 인터페이스."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("MOW 재고·매출·재무 관리")
        master.geometry("1024x720")
        self.theme = ThemeManager(master)
        self.db = DatabaseManager()
        self.reporter = ReportGenerator(self.db)
        self.sync_manager = SyncManager(self.db)

        self.notebook = ttk.Notebook(master)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_inventory_tab()
        self._build_sales_tab()
        self._build_reports_tab()
        self._build_dashboard_tab()
        self._build_tax_tab()
        self._build_sync_tab()
        self._build_backup_tab()
        self.refresh_products()
        self.refresh_sales()
        self.refresh_dashboard()
        self.sync_manager.export_documents()

    # Inventory tab ------------------------------------------------------
    def _build_inventory_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="재고 관리")

        form = ttk.LabelFrame(frame, text="상품 등록/수정")
        form.pack(fill=tk.X, padx=10, pady=10)

        self.product_code = tk.StringVar()
        self.product_name = tk.StringVar()
        self.product_cost = tk.DoubleVar(value=0.0)
        self.product_price = tk.DoubleVar(value=0.0)
        self.product_stock = tk.IntVar(value=0)
        self.product_reorder = tk.IntVar(value=5)

        self._add_labeled_entry(form, "상품코드", self.product_code, 0)
        self._add_labeled_entry(form, "상품명", self.product_name, 1)
        self._add_labeled_entry(form, "매입단가", self.product_cost, 2)
        self._add_labeled_entry(form, "판매가", self.product_price, 3)
        self._add_labeled_entry(form, "초기 재고", self.product_stock, 4)
        self._add_labeled_entry(form, "재주문 기준", self.product_reorder, 5)

        ttk.Button(form, text="상품 저장", command=self.save_product).grid(row=0, column=6, rowspan=2, padx=10)
        ttk.Button(form, text="재고 추가", command=self.prompt_restock).grid(row=2, column=6, rowspan=2, padx=10)

        self.products_tree = ttk.Treeview(frame, columns=("code", "name", "cost", "price", "stock", "reorder"), show="headings")
        headings = {
            "code": "상품코드",
            "name": "상품명",
            "cost": "매입단가",
            "price": "판매가",
            "stock": "재고",
            "reorder": "재주문 기준",
        }
        for col, label in headings.items():
            self.products_tree.heading(col, text=label)
        self.products_tree.tag_configure("odd", background=self.theme.config.tree_stripe)
        self.products_tree.tag_configure("even", background=self.theme.config.surface)
        self.products_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.low_stock_label = ttk.Label(frame, text="재고 부족 상품이 여기 표시됩니다.")
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
            messagebox.showinfo("상품", "상품 정보가 저장되었습니다.")
            self._after_data_change()
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("오류", str(exc))

    def prompt_restock(self) -> None:
        code = self.product_code.get()
        qty = simpledialog.askinteger("재고 추가", "추가 수량", minvalue=1)
        if not qty:
            return
        try:
            self.db.restock(code, qty)
            messagebox.showinfo("재고 추가", "재고가 갱신되었습니다.")
            self._after_data_change()
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("오류", str(exc))

    def refresh_products(self) -> None:
        for item in self.products_tree.get_children():
            self.products_tree.delete(item)
        for idx, product in enumerate(self.db.fetch_products()):
            tag = "odd" if idx % 2 else "even"
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
                tags=(tag,),
            )
        low = self.db.get_low_stock()
        if low:
            summary = ", ".join(f"{p['name']} ({p['stock']}개)" for p in low)
            self.low_stock_label.config(text=f"재고 부족: {summary}")
        else:
            self.low_stock_label.config(text="모든 상품 재고가 안정적입니다.")

    # Sales tab ----------------------------------------------------------
    def _build_sales_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="판매")

        form = ttk.LabelFrame(frame, text="판매 등록")
        form.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(form, text="상품").grid(row=0, column=0, padx=5, pady=5)
        self.sale_product = tk.StringVar()
        self.sale_product_combo = ttk.Combobox(form, textvariable=self.sale_product, state="readonly")
        self.sale_product_combo.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(form, text="수량").grid(row=0, column=2, padx=5, pady=5)
        self.sale_qty = tk.IntVar(value=1)
        ttk.Entry(form, textvariable=self.sale_qty, width=10).grid(row=0, column=3, padx=5, pady=5)

        ttk.Button(form, text="판매 등록", command=self.record_sale).grid(row=0, column=4, padx=5, pady=5)

        self.sales_tree = ttk.Treeview(frame, columns=("date", "product", "qty", "price"), show="headings")
        sale_headings = {
            "date": "판매일",
            "product": "상품명",
            "qty": "수량",
            "price": "판매가",
        }
        for col, label in sale_headings.items():
            self.sales_tree.heading(col, text=label)
        self.sales_tree.tag_configure("odd", background=self.theme.config.tree_stripe)
        self.sales_tree.tag_configure("even", background=self.theme.config.surface)
        self.sales_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def record_sale(self) -> None:
        code = self.sale_product.get()
        qty = int(self.sale_qty.get())
        try:
            sale = self.db.record_sale(code, qty)
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("판매", str(exc))
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
            "판매",
            f"매출액: {sale['revenue']:.2f}\n매출원가: {sale['cogs']:.2f}\n세금계산서가 저장되었습니다.",
        )
        self._after_data_change()

    def save_invoice(self, invoice: TaxInvoice) -> None:
        invoices_dir = DATA_DIR / "invoices"
        invoices_dir.mkdir(parents=True, exist_ok=True)
        filename = invoices_dir / f"invoice_{invoice.product_code}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(filename, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(["상품 코드", "상품명", "수량", "단가", "공급가액", "부가세", "총액"])
            writer.writerow(invoice.to_row())

    def refresh_sales(self) -> None:
        for item in self.sales_tree.get_children():
            self.sales_tree.delete(item)
        products = {p["product_code"]: p for p in self.db.fetch_products()}
        for idx, sale in enumerate(self.db.fetch_sales()):
            tag = "odd" if idx % 2 else "even"
            self.sales_tree.insert(
                "",
                tk.END,
                values=(sale["sale_date"], sale["name"], sale["quantity"], f"{sale['sale_price']:.2f}"),
                tags=(tag,),
            )
        codes = list(products.keys())
        self.sale_product_combo["values"] = codes
        if codes and not self.sale_product.get():
            self.sale_product.set(codes[0])

    # Reports tab --------------------------------------------------------
    def _build_reports_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="재무 보고")

        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, padx=10, pady=10)

        current = dt.date.today()
        self.report_year = tk.IntVar(value=current.year)
        self.report_month = tk.IntVar(value=current.month)

        ttk.Label(controls, text="연도").grid(row=0, column=0, padx=5)
        ttk.Entry(controls, textvariable=self.report_year, width=6).grid(row=0, column=1, padx=5)
        ttk.Label(controls, text="월").grid(row=0, column=2, padx=5)
        ttk.Entry(controls, textvariable=self.report_month, width=4).grid(row=0, column=3, padx=5)
        ttk.Button(controls, text="보고서 보기", command=self.display_report).grid(row=0, column=4, padx=5)
        ttk.Button(controls, text="엑셀로 내보내기", command=self.export_reports).grid(row=0, column=5, padx=5)

        self.report_text = tk.Text(
            frame,
            height=20,
            bg=self.theme.config.surface,
            fg=self.theme.config.text_color,
        )
        self.report_text.configure(insertbackground=self.theme.config.text_color)
        self.report_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def display_report(self) -> None:
        summary = self.db.get_monthly_summary(self.report_year.get(), self.report_month.get())
        lines = ["월간 재무 요약"]
        for key, label in [
            ("revenue", "매출액"),
            ("cogs", "매출원가"),
            ("gross_profit", "매출총이익"),
            ("income_tax", "소득세"),
            ("net_income", "당기순이익"),
            ("cash_flow", "영업현금흐름"),
            ("inventory_value", "재고 자산"),
            ("cash_balance", "현금 잔액"),
        ]:
            lines.append(f"{label}: {summary[key]:,.2f}")
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, "\n".join(lines))

    def export_reports(self) -> None:
        year = self.report_year.get()
        month = self.report_month.get()
        file_path = filedialog.asksaveasfilename(
            title="보고서 저장",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not file_path:
            return
        self.reporter.export_monthly_reports(year, month, Path(file_path))
        messagebox.showinfo("재무 보고", "엑셀 파일이 저장되었습니다.")

    # Dashboard ---------------------------------------------------------
    def _build_dashboard_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="그래프 분석")

        self.figure = Figure(figsize=(6, 4), dpi=110)
        self.figure.patch.set_facecolor(self.theme.config.surface)
        self.chart_ax = self.figure.add_subplot(111)
        self.chart_ax.set_facecolor(self.theme.config.background)
        self.chart_canvas = FigureCanvasTkAgg(self.figure, master=frame)
        self.chart_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Button(frame, text="그래프 새로고침", command=self.refresh_dashboard).pack(pady=5)

    def refresh_dashboard(self) -> None:
        if not hasattr(self, "chart_ax"):
            return
        data = self.db.get_monthly_trends(12)
        self.chart_ax.clear()
        self.chart_ax.set_facecolor(self.theme.config.surface)
        self.figure.patch.set_facecolor(self.theme.config.surface)
        if not data:
            self.chart_ax.text(
                0.5,
                0.5,
                "표시할 매출 데이터가 없습니다.",
                ha="center",
                va="center",
                color=self.theme.config.text_color,
                fontsize=14,
            )
            self.chart_canvas.draw_idle()
            return
        periods = [row["period"] for row in data]
        metrics = {
            "매출": {
                "values": [row["revenue"] for row in data],
                "color": "#22c55e",
            },
            "영업이익": {
                "values": [row["gross_profit"] for row in data],
                "color": "#0ea5e9",
            },
            "부가세": {
                "values": [row["vat"] for row in data],
                "color": "#f97316",
            },
            "소득세": {
                "values": [row["income_tax"] for row in data],
                "color": "#e11d48",
            },
        }
        for label, meta in metrics.items():
            self.chart_ax.plot(
                periods,
                meta["values"],
                label=label,
                linewidth=2.2,
                marker="o",
                markersize=6,
                color=meta["color"],
            )
        self.chart_ax.set_title("최근 12개월 매출·이익·세금 추세", color=self.theme.config.text_color)
        self.chart_ax.tick_params(axis="x", rotation=45, labelcolor=self.theme.config.text_color)
        self.chart_ax.tick_params(axis="y", labelcolor=self.theme.config.text_color)
        self.chart_ax.spines["top"].set_visible(False)
        self.chart_ax.spines["right"].set_visible(False)
        self.chart_ax.spines["left"].set_color(self.theme.config.border_color)
        self.chart_ax.spines["bottom"].set_color(self.theme.config.border_color)
        legend = self.chart_ax.legend(facecolor=self.theme.config.surface, edgecolor=self.theme.config.border_color)
        for text in legend.get_texts():
            text.set_color(self.theme.config.text_color)
        self.figure.tight_layout()
        self.chart_canvas.draw_idle()

    # Sync tab ----------------------------------------------------------
    def _build_sync_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="문서 동기화")

        desc = (
            "동일한 데이터를 엑셀(.xlsx)과 TSV(.tsv) 파일로 자동 저장하고, 문서에서 수정한 내용을 다시 불러올 수 있습니다."
        )
        ttk.Label(frame, text=desc, wraplength=880).pack(padx=10, pady=10)

        path_frame = ttk.Frame(frame)
        path_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(path_frame, text="엑셀 파일 경로:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(path_frame, text=str(EXCEL_SYNC_PATH)).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(path_frame, text="TSV 파일 경로:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Label(path_frame, text=str(TSV_SYNC_PATH)).grid(row=1, column=1, sticky=tk.W, pady=5)

        buttons = ttk.Frame(frame)
        buttons.pack(pady=10)
        ttk.Button(buttons, text="동기화 파일 수동 저장", command=self.sync_export_documents).grid(row=0, column=0, padx=5)
        ttk.Button(buttons, text="엑셀에서 불러오기", command=self.sync_import_excel).grid(row=0, column=1, padx=5)
        ttk.Button(buttons, text="TSV에서 불러오기", command=self.sync_import_tsv).grid(row=0, column=2, padx=5)

        ttk.Label(
            frame,
            text="엑셀 파일에서는 products, sales, tax_settings 시트를 수정할 수 있으며 컬럼 이름을 유지해야 합니다.",
        ).pack(padx=10, pady=5)

    def sync_export_documents(self) -> None:
        try:
            excel, tsv = self.sync_manager.export_documents()
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("문서 동기화", str(exc))
            return
        messagebox.showinfo("문서 동기화", f"엑셀: {excel}\nTSV: {tsv}\n위치에 저장되었습니다.")

    def sync_import_excel(self) -> None:
        file_path = filedialog.askopenfilename(title="엑셀 선택", filetypes=[("Excel", "*.xlsx")])
        if not file_path:
            return
        try:
            self.sync_manager.import_from_excel(Path(file_path))
            self._after_data_change()
            messagebox.showinfo("문서 동기화", "엑셀 내용이 반영되었습니다.")
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("문서 동기화", str(exc))

    def sync_import_tsv(self) -> None:
        file_path = filedialog.askopenfilename(title="TSV 선택", filetypes=[("TSV", "*.tsv")])
        if not file_path:
            return
        try:
            self.sync_manager.import_from_tsv(Path(file_path))
            self._after_data_change()
            messagebox.showinfo("문서 동기화", "TSV 내용이 반영되었습니다.")
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("문서 동기화", str(exc))

    # Tax tab ------------------------------------------------------------
    def _build_tax_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="세금")

        rates = self.db.get_tax_rates()
        self.vat_rate = tk.DoubleVar(value=rates["vat_rate"])
        self.income_tax_rate = tk.DoubleVar(value=rates["income_tax_rate"])

        ttk.Label(frame, text="부가세율(소수)").grid(row=0, column=0, padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.vat_rate).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(frame, text="소득세율(소수)").grid(row=1, column=0, padx=5, pady=5)
        ttk.Entry(frame, textvariable=self.income_tax_rate).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(frame, text="세율 저장", command=self.save_tax_rates).grid(row=2, column=0, columnspan=2, pady=10)

    def save_tax_rates(self) -> None:
        try:
            self.db.update_tax_rates(float(self.vat_rate.get()), float(self.income_tax_rate.get()))
            messagebox.showinfo("세금", "세율이 저장되었습니다.")
            self._after_data_change()
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("세금", str(exc))

    # Backup tab ---------------------------------------------------------
    def _build_backup_tab(self) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="백업")

        ttk.Button(frame, text="백업 생성", command=self.create_backup).pack(padx=10, pady=10)
        ttk.Button(frame, text="백업 복원", command=self.restore_backup).pack(padx=10, pady=10)

    def create_backup(self) -> None:
        backup_path = filedialog.asksaveasfilename(
            title="데이터베이스 백업",
            defaultextension=".db",
            initialfile=f"backup_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
        )
        if not backup_path:
            return
        self.db.backup(Path(backup_path))
        messagebox.showinfo("백업", "백업 파일이 생성되었습니다.")

    def restore_backup(self) -> None:
        source = filedialog.askopenfilename(title="백업 파일 선택", filetypes=[("DB", "*.db")])
        if not source:
            return
        self.db.restore(Path(source))
        messagebox.showinfo("백업", "데이터베이스를 복원했습니다.")
        self._after_data_change()

    # Helpers -----------------------------------------------------------
    def _auto_sync(self) -> None:
        try:
            self.sync_manager.export_documents()
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showwarning("문서 동기화", f"자동 저장 중 오류가 발생했습니다: {exc}")

    def _after_data_change(self) -> None:
        self.refresh_products()
        self.refresh_sales()
        self.refresh_dashboard()
        self._auto_sync()


def main() -> None:
    root = tk.Tk()
    InventoryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
