# MOW

Market Orchestrator on Web for personal use.

## Inventory, Sales, and Finance Application

This repository now includes `inventory_app.py`, a Tkinter desktop application
that automates inventory tracking, sales management, tax calculation, and
monthly financial reporting using an SQLite database.

### Features

* **Inventory management** – track product cost, sale price, stock quantity,
  and reorder thresholds. Purchases automatically update inventory movements
  and cash flow.
* **Sales & profit tracking** – record sales, update stock, compute COGS,
  gross profit, and automatically generate CSV tax invoices per transaction.
* **Automated taxes** – VAT and income tax are calculated from configurable
  tax rates. The interface allows updating the rates at any time.
* **Financial reporting** – create monthly profit & loss, balance sheet, and
  cash flow statements viewable inside the app and exportable to Excel via
  pandas.
* **Database backup & restore** – create timestamped backups of the SQLite
  database or restore from an existing file.

### Getting Started

1. Install dependencies:

   ```bash
   pip install pandas
   ```

2. Run the application:

   ```bash
   python inventory_app.py
   ```

3. Use the tabs to add products, record sales, review financial statements,
   manage tax rates, and perform backups.

### Testing

You can perform a quick syntax check of the desktop application with:

```bash
python -m py_compile inventory_app.py
```

Running the command regularly ensures that the code remains free of syntax
errors before shipping updates or generating release builds.
