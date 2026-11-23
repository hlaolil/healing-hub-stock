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
| `SHOP_MODE` | `1` on the shop computer (docker-compose sets it). Sales never wait for the network |
| `CLOUD_MONGODB_URI` | Shop computer only: the Atlas connection string the shop syncs with |
| `READ_ONLY` | Optional: `1` forces a copy to stay view-only. Normally the app decides, from who is in charge |
| `UPLOAD_WARN_DAYS` | Warn admins in the shop when the last sync is older than this (default `3`) |
| `OWNER_WHATSAPP` | Owner's number for the WhatsApp summary and alerts, e.g. `26658000000` |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `OWNER_EMAIL` | Optional: also allow the owner messages by email |
| `CRON_SECRET` | Optional: protects `/api/cron/daily` if you schedule it yourself |
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

29 suites, 1,969 checks, run against an in-memory database. `tests/test_pos.py` covers the till, receipts, voids, cash-up and the public feed.

## Run it on your own computer

You need **Python 3.12**, **Git** and **Docker Desktop** (for the database).

1. Start a local database (MongoDB) in the background:
   ```bash
   docker compose up -d mongo
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


**Tests** use a fake database, so they don't need Docker: `python tests/run_all.py`.

Your local data lives only in the Docker volume on your computer. `docker compose down` stops the database and keeps the data; `docker compose down -v` deletes it.

## The shop computer and the online copy

The pharmacy sells from **one computer in the shop** that runs the app and its own
database in Docker. Tills, phones and laptops on the shop Wi-Fi open it, so no
internet is needed to sell, receive or count stock.

1. Install Docker Desktop and set it to start when the computer starts.
2. `cp .env.example .env`, then fill in `SECRET_KEY`, `ADMIN_PASSWORD`,
   `CLOUD_MONGODB_URI` (the Atlas connection string) and `OWNER_WHATSAPP`.
3. `docker compose up -d --build`. The app is at `http://<shop computer's IP>:5000`.

**Taking turns.** The shop copy and the online copy (Vercel, on the same Atlas
database as `CLOUD_MONGODB_URI`) take turns being *in charge*. The copy in charge
accepts changes; the other is view-only and says so on every page. So the two can
never disagree. From the shop's **Owner Reports**, when connected:

| Button | What happens |
| --- | --- |
| **Upload** | Shop changes go up. The shop stays in charge |
| **Upload and hand over to online** | Shop changes go up, and online takes charge: work away from the shop |
| **Bring back to shop** | Changes made online come down, and the shop takes charge again |

Only records that changed since the last sync move, so a sync is quick on mobile
data; one cut off half way simply finishes next time, and control only changes hands
when the sync succeeds. **Full upload** (shop in charge only) checks every record and
repairs an online copy that was changed by hand.

**Emergencies.** If the network is down when the shop must sell, or the shop computer
is broken when work must go on online, the copy that needs it can **take charge here
now** (Owner Reports, ticked to confirm). The next sync from the shop brings both copies
level. A record changed in both places keeps the shop's version and is listed on Owner
Reports for checking; for a stock item, a quick count settles it. Sales made in both
places are all kept.

**Backups.** Until the next upload, the shop computer holds the only copy of the
latest sales. Sync at least every few days, and download a backup from `/backup` regularly.

## From HealthRecords (23 Nov 2026)

- **Several invoices per delivery**: one consignment can come with several
  invoices, and an invoice that arrives later can be added to an open delivery.
- **Monthly indicators on the dashboard** for the staff meeting: stock-out rate
  against a 10% objective (items at zero for over six months are left out),
  expired medicine and its cost, and full stock counts against two a year.
- **Medication Errors** (`/meeting-log`): dispensing, labelling, prescribing and
  near-miss errors, counted on the dashboard. No patient or staff names.
- **Stock take**: a whole sheet of "agrees" ticks posts as one small request;
  Download CSV keeps the stock take; a CSV count sheet for the Stock Take phone app.
- Table headings stay in view while scrolling.

## WhatsApp messages

Messages are written by the app and sent by a person: each button opens WhatsApp
with the text filled in, and someone presses Send. No Meta account, approval or
fees are needed.

- **Owner Reports → Send on WhatsApp**: today's summary, and the weekly alerts
  (best on `WEEKLY_ALERT_DAY`), to `OWNER_WHATSAPP`.
- **Refill calls** (`/refills`): chronic patients due within a week or up to 60
  days late. **WhatsApp** opens the reminder for that patient and marks it sent.
  The message never names the medicine. Patients without a number are phoned.

Local numbers (8 digits) get Lesotho's code, 266, added.

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

