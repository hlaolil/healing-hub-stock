# The Healing Hub Pharmacy — Stock & Point of Sale

A Flask + MongoDB app that runs the pharmacy's stock and till: selling at the counter, receiving deliveries, stock takes, expiry, the controlled drug register, fridge temperatures, reports, and the product list shown on the Healing Hub website.

Adapted from the HealthRecords clinic pharmacy app. The clinic-only parts (department requests, equipment loans, store key register, diagnoses and sick leave) were removed. Point of sale, selling prices and the public product feed were added.

## What it does

| Page | For |
| --- | --- |
| **Point of Sale** (`/sell`) | Ring up a basket, take payment (Cash, M-Pesa, EcoCash, Card, Medical aid), print a receipt. Stock drops automatically. |
| **Sales** (`/sales`) | Today's cash-up by payment method, gross profit (admins), every receipt, CSV download. Admins can void a sale, which returns its stock. |
| **Receiving** | Deliveries against supplier orders and invoices; sets each item's cost. |
| **Write-offs** | Damaged, spoiled or lost stock (expired stock is cleared from Reports). |
| **Stock Take** | Count the shelves and correct the balances, with variances recorded. |
| **Temperature** | Morning and afternoon max/min readings for the dispensary, stores and fridge. |
| **Reports** | Stock on hand, expiry, losses, unmet demand, inventory with AMC, order request, receive list, controlled drug register, period report. |
| **Dashboard** | Monthly movement, stock value, fill rate, expiring stock. |
| **Add / Edit Medication** | Cost per pack, **customer price**, prescription-only flag, and whether and how it appears on the website. |

### How a sale works

- Each line is written as an ordinary stock movement, so every existing report and the controlled drug register keep working. The receipt (payment, totals, receipt number `HH-YYYYMMDD-0001`) is kept in the `sales` collection.
- Cost and selling price are stored separately on every line, so gross profit is exact and a later price change never rewrites a past sale.
- A sale is all-or-nothing. If an item is short, unknown or has no price, nothing is sold and the cashier is told why. A shortfall is still recorded as unmet demand, which feeds the order request.
- Prescription-only items need the patient's name and prescription number. Controlled items also need the prescriber, for the register.

### The website product feed

`GET /api/public/products` is the only page that needs no login. It lists items an admin has ticked **Show on website**, with:

- name, category, short description
- price for over-the-counter items, and **no price for prescription-only items**
- `in_stock: true/false`, never the quantity
- no costs

The Healing Hub website reads it (set `STOCK_API_URL` there) and caches it for a few minutes.

## Setup

Environment variables:

| Variable | Purpose |
| --- | --- |
| `MONGODB_URI` | MongoDB Atlas connection string |
| `MONGODB_DB` | Database name, default `healing_hub`. The app refuses `pharmacy_db` (the NMC clinic's database), so the two apps can share one Atlas cluster without sharing data |
| `WEBSITE_URL` | The public website, e.g. `https://healinghubpharmacy.vercel.app`. Chronic sales send refill reminders there |
| `TILL_SYNC_SECRET` | Long random string, **the same** as on the website. Proves reminders come from the till |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD` | The pharmacy Gmail account and its 16-letter app password, for the owner emails |
| `OWNER_EMAIL` | Where the daily summary and weekly alerts go (default: `GMAIL_USER`) |
| `CRON_SECRET` | Long random string; Vercel Cron sends it so only Vercel can run the evening job |
| `WEEKLY_ALERT_DAY` | Day for the weekly alerts: `Mon`…`Sun` (default `Thu`, so orders go in before the weekend) |
| `MARKUP_PERCENT` | Markup used for suggested prices and below-cost warnings (default `82`, the 45% gross margin in the business plan) |
| `SECRET_KEY` | Long random string; the app refuses to start without it |
| `ADMIN_PASSWORD` | Needed to open the Register page and create accounts |
| `WEBSITE_ORIGIN` | Optional: the website's address, e.g. `https://healinghubpharmacy.vercel.app`, to allow only it to read the feed (defaults to any site) |
| `PHARMACY_UTC_OFFSET` | Optional, default `2` (Lesotho) |

On Vercel, import the repository. `vercel.json` tells Vercel this is a Flask app: it builds `app.py` with the Python runtime, sends every request to it, and includes the `templates/` folder. Set `MONGODB_URI` and `SECRET_KEY` before the first deploy — without `SECRET_KEY` the app refuses to start, and without a reachable database every request waits up to two minutes. Locally:

```bash
pip install -r requirements.txt
SECRET_KEY=dev MONGODB_URI=mongodb://localhost:27017/ python app.py
```

### First steps

1. Open `/register`, enter `ADMIN_PASSWORD`, and create an **Admin** account, then accounts for staff (**Employee**).
2. Under **Add Medication**, set up each product: cost per pack, customer price, prescription-only, and website listing. Use an opening balance for stock already on the shelf.
3. Sell from **Point of Sale**; cash up from **Sales** at the end of the day.

## Tests

```bash
pip install mongomock
python tests/run_all.py
```

24 suites, 1,764 checks, run against an in-memory database. `tests/test_pos.py` covers the till, receipts, voids, cash-up and the public feed.

## Run it on your own computer

You need **Python 3.12**, **Git** and **Docker Desktop** (for the database).

1. Start a local database (MongoDB) in the background:
   ```bash
   docker compose up -d
   ```
2. Create a virtual environment and install the packages:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Copy the settings file and adjust it if you like:
   ```bash
   cp .env.example .env             # Windows: copy .env.example .env
   ```
4. Start the app:
   ```bash
   python app.py
   ```
   Open http://localhost:5000, go to `/register`, enter the `ADMIN_PASSWORD` from `.env`, and create your admin account.

On a Mac, if port 5000 is taken (AirPlay Receiver uses it), set `PORT=5001` in `.env` and use that port everywhere below.

**With the website:** run the website too (see its README). The website reads products from this app and this app sends refill reminders to the website, so both `.env` files must point at each other and share the same `TILL_SYNC_SECRET`.

**The evening job by hand** (owner emails and reminder retries):
```bash
curl -H "Authorization: Bearer local-cron-secret" http://localhost:5000/api/cron/daily
```

**Tests** use a fake database, so they don't need Docker: `python tests/run_all.py`.

Your local data lives only in the Docker volume on your computer. `docker compose down` stops the database and keeps the data; `docker compose down -v` deletes it.

## Retail features

- **Point of sale** (`/sell`): scan a barcode (a USB scanner types the code and presses Enter) or type the item name. M-Pesa and EcoCash sales need the transaction code from the confirmation SMS.
- **Chronic medicines**: tick *Chronic* on a product and enter how many units a patient takes a day. When the till sells it to a patient who agrees to reminders, it tells the website, which emails them 3 days before the supply runs out (or lists them for a phone call if they have no email). A repeat purchase moves the date on. The medicine name is never sent.
- **Paper receipts**: when the internet or power is down, write paper receipts; enter them later under *Entering a paper receipt?* on the till. They are dated when they happened and wait on the Sales page for an admin to approve them against the paper copy.
- **Pricing guard**: product forms suggest a selling price from the cost at `MARKUP_PERCENT`, and saving a price below cost shows a warning.
- **Owner Reports** (`/owner-reports`, admin): refill adherence (refills collected on time), items running low, stock expiring within 90 days, items priced below cost, and the last price paid to each supplier.
- **Owner emails**: every evening at 18:30 (Vercel Cron, `vercel.json`) the owner gets the day's sales by payment method, voids, write-offs, late paper entries, unmet demand and missing temperature readings. On `WEEKLY_ALERT_DAY` the weekly alerts come too. The same job retries refill reminders that could not reach the website.
- **Spreadsheet uploads** (Excel or CSV; every upload is shown for checking first, and nothing changes until you press the page's own button):
  - *Add Medication*: load many new products at once, with cost, opening stock, batch and expiry, and the shop columns (selling price, prescription only, show on website, website category, chronic, units per day, barcode). Download the template from the page.
  - *Receiving*: read a supplier's invoice spreadsheet into the delivery (units or packs, pack or unit prices or line totals; Total and VAT rows are skipped; expiries like "12/26" are read).
  - *Stock Take*: download a count sheet by shelf group (pharmaceuticals, supplies, controlled drugs), fill it in, upload it, then post. A count posted wrongly can be edited later; stock moves by the difference only.
  - Half-checked uploads are kept as drafts until posted or discarded.
- **Product codes and renames**: every product gets a permanent code (MED-0001 ...; an official code can replace it). Renaming a product moves its stock records, stock-take counts and till receipts to the new name, and the old name still matches in spreadsheets. Many products can be renamed at once from a list on the Add Medication page.

These upload, code and rename features come from HealthRecords (November 2026), adapted for the shop.

