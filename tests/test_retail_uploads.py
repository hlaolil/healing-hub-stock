"""Healing Hub's own fields in the spreadsheet uploads, codes and renames.

The upload features come from HealthRecords; these checks cover what the
shop adds on top: selling price, prescription only, website, chronic and
barcode columns on a list of new products, and a rename carrying the till's
sales history with it.
"""
from _root import ROOT  # the app folder, one up from tests/
import os
os.environ['SECRET_KEY'] = 'k'
import io, re, html as _html
import mongomock, pymongo, openpyxl
from datetime import datetime, timezone

_f = mongomock.MongoClient()
pymongo.MongoClient = lambda *a, **k: _f
import app as A
A.get_mongo_client = lambda _client=_f: _client
A.init_db_collections()
from test_support import arm_csrf, sell
db = _f['healing_hub']
meds, txs, sales = db['medications'], db['transactions'], db['sales']
c = A.app.test_client()
arm_csrf(c)
PASS, FAIL = [], []


def check(label, cond, detail=''):
    (PASS if cond else FAIL).append(label)
    print(('  PASS  ' if cond else '  FAIL  ') + label
          + (('  ->  ' + detail) if detail and not cond else ''))


def login(role='admin', name='Letlotlo Hlaoli'):
    with c.session_transaction() as s:
        s['user'] = {'name': name, 'login': 'admin', 'role': role}
        s['last_active'] = datetime.now(timezone.utc).isoformat()


def xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()


def post_file(url, data, content):
    d = dict(data)
    d['sheet'] = (io.BytesIO(content), 'sheet.xlsx')
    return c.post(url, data=d, content_type='multipart/form-data', follow_redirects=True)


def banner(page):
    m = re.search(r'<p class="message[^"]*"[^>]*>(.*?)</p>', page, re.S)
    return _html.unescape(m.group(1)).strip() if m else ''


def reset():
    for col in db.list_collection_names():
        db[col].delete_many({})


HEAD = ['Medication', 'Category', 'Schedule', 'Pack size', 'Price per pack', 'Opening balance',
        'Batch', 'Expiry date', 'Code', 'Selling price', 'Prescription only', 'Show on website',
        'Website category', 'Chronic', 'Units per day', 'Barcode', 'Website description']


def post_review(page):
    """Press Add These Items with the review table as the page shows it."""
    form = {'action': 'meds_bulk', 'n': re.search(r'name="n" value="(\d+)"', page).group(1)}
    for f in ('name', 'code', 'pack_size', 'pack_price', 'opening', 'batch', 'expiry',
              'status', 'note'):
        for i, v in re.findall(r'name="' + f + r'__(\d+)" value="([^"]*)"', page):
            form[f'{f}__{i}'] = _html.unescape(v)
    for f in ('category', 'schedule'):
        for i, body in re.findall(r'<select name="' + f + r'__(\d+)"[^>]*>(.*?)</select>', page, re.S):
            form[f'{f}__{i}'] = re.search(r'<option value="([^"]+)" selected', body).group(1)
    for i, v in re.findall(r"name=\"retail__(\d+)\" value='([^']*)'", page):
        form[f'retail__{i}'] = _html.unescape(v)
    for i in re.findall(r'name="inc__(\d+)" value="1"\s*checked', page):
        form[f'inc__{i}'] = '1'
    return c.post('/add-medication', data=form, follow_redirects=True)


print('\n--- 1. The product template carries the shop columns ---')
reset(); login()
r = c.get('/upload-template/medications')
ws = openpyxl.load_workbook(io.BytesIO(r.data)).active
heads = [x.value for x in ws[1]]
check('the template has selling price, website, chronic and barcode columns',
      all(h in heads for h in ('Selling price', 'Show on website', 'Chronic', 'Units per day', 'Barcode')),
      str(heads))
check('the checklist template is gone (clinic only)',
      c.get('/upload-template/checklist').status_code == 302)

print('\n--- 2. A list of new products with shop fields ---')
reset(); login()
sheet = xlsx([HEAD,
              ['Amlodipine tabs, 5 mg', '', '', 30, 9.0, 60, 'AM1', '2028-06-30', '', 0.55,
               'Yes', 'No', '', 'Yes', 1, 6009876543210, ''],
              ['Cetirizine tabs, 10 mg', '', '', 30, 18.5, 30, 'CT1', '12/27', '', 1.20,
               'No', 'Yes', 'Over-the-counter medicines', 'No', '', '6001234567890',
               'For hay fever.'],
              ['Cheap syrup 100 ml', '', '', 1, 30.0, 0, '', '', '', 20.0, '', 'yes', '', '', '', '', ''],
              ['Odd web item', '', '', 1, 5.0, 0, '', '', '', 9, '', 'yes', 'Snacks', '', '', 'bad code!', '']])
r = post_file('/add-medication', {'action': 'upload_meds'}, sheet)
page = r.data.decode()
d = db['upload_drafts'].find_one({'kind': 'medications'})
rows = {x['name']: x for x in d['rows']}
am = rows['Amlodipine tabs, 5 mg']['retail']
check('selling price, prescription only and chronic are read',
      am['selling_price'] == 0.55 and am['rx_only'] and am['chronic'] and am['units_per_day'] == 1, str(am))
check('a barcode Excel stored as a number is read whole', am['barcode'] == '6009876543210', str(am))
ce = rows['Cetirizine tabs, 10 mg']
check('website, category and description are read',
      ce['retail']['on_website'] and ce['retail']['web_category'] == 'Over-the-counter medicines'
      and ce['retail']['description'] == 'For hay fever.', str(ce['retail']))
check('a month-and-year expiry is read to the end of the month', ce['expiry'] == '2027-12-31', ce['expiry'])
odd = rows['Odd web item']
check('an unknown website category and a bad barcode are flagged',
      'website category' in odd['problem'] and 'barcode' in odd['problem'], odd['problem'])
check('the review table shows the shop fields',
      'M0.55 each' in page and 'Chronic, 1.0/day' in page and 'On website' in page)
check('nothing is added before checking', meds.count_documents({}) == 0)

r = post_review(page)
msg = banner(r.data.decode())
a = meds.find_one({'name': 'Amlodipine tabs, 5 mg'})
check('the ticked products are added', meds.count_documents({}) == 3, msg)
check('with their shop fields', a and a['selling_price'] == 0.55 and a['rx_only'] and a['chronic']
      and a['barcode'] == '6009876543210', str(a))
check('each gets a product code', a and re.fullmatch(r'MED-\d{4}', a.get('code') or ''), str(a and a.get('code')))
check('opening stock is recorded', a and a['balance'] == 60
      and txs.count_documents({'type': 'opening_balance', 'med_name': 'Amlodipine tabs, 5 mg'}) == 1)
check('a product priced below cost is named in the message', 'Priced below cost: Cheap syrup 100 ml' in msg, msg)
check('the flagged row was left out', not meds.find_one({'name': 'Odd web item'}))
feed = c.get('/api/public/products').get_json()
names = [p['name'] for p in feed['products']]
check('website items appear in the public feed straight away',
      'Cetirizine tabs, 10 mg' in names and 'Amlodipine tabs, 5 mg' not in names, str(names))

print('\n--- 3. A barcode already in use is refused on upload ---')
sheet = xlsx([HEAD, ['Loratadine tabs, 10 mg', '', '', 30, 15, 0, '', '', '', 1.0, '', '', '', '', '',
                     '6001234567890', '']])
page = post_file('/add-medication', {'action': 'upload_meds'}, sheet).data.decode()
r = post_review(page)
check('the clash is named and nothing is added',
      'already used by Cetirizine' in banner(r.data.decode()) and not meds.find_one({'name': 'Loratadine tabs, 10 mg'}),
      banner(r.data.decode()))

print('\n--- 4. Renaming carries the till history ---')
sell(c, db, [('Amlodipine tabs, 5 mg', 30)], customer='P', prescription_no='RX1')
old_sales = sales.count_documents({'lines.name': 'Amlodipine tabs, 5 mg'})
a = meds.find_one({'name': 'Amlodipine tabs, 5 mg'})
form = {'med_name': a['name'], 'new_name': 'Amlodipine tablets, 5 mg', 'code': a['code'],
        'batch': a['batch'], 'category': a['category'], 'pack_size': '30', 'pack_price': '9',
        'expiry_date': '2028-06-30', 'schedule': 'not controlled', 'selling_price': '0.55',
        'rx_only': 'on', 'chronic': 'on', 'units_per_day': '1', 'barcode': a['barcode']}
r = c.post('/edit-medication', data=form, follow_redirects=True)
check('the sale existed under the old name', old_sales == 1)
check('the product is renamed and keeps its code',
      meds.find_one({'name': 'Amlodipine tablets, 5 mg', 'code': a['code']}) is not None,
      banner(r.data.decode()))
check('its receipts now carry the new name',
      sales.count_documents({'lines.name': 'Amlodipine tablets, 5 mg'}) == 1
      and sales.count_documents({'lines.name': 'Amlodipine tabs, 5 mg'}) == 0)
check('and its stock records', txs.count_documents({'med_name': 'Amlodipine tabs, 5 mg'}) == 0)
check('the old name still finds it in a spreadsheet',
      'Amlodipine tabs, 5 mg' in (meds.find_one({'name': 'Amlodipine tablets, 5 mg'}).get('former_names') or []))

print(f"\n=========  {len(PASS)} passed, {len(FAIL)} failed  =========")
if FAIL:
    for f in FAIL:
        print('  FAILED:', f)
