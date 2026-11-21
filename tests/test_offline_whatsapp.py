"""The shop computer and the online copy, and messages by WhatsApp."""
from _root import ROOT  # the app folder, one up from tests/
import os
os.environ['SECRET_KEY'] = 'k'
os.environ.pop('WEBSITE_URL', None)
import mongomock, pymongo
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

_f = mongomock.MongoClient()
pymongo.MongoClient = lambda *a, **k: _f
import app as A
A.get_mongo_client = lambda _client=_f: _client
A.init_db_collections()
db = _f['healing_hub']
_cloud_client = mongomock.MongoClient()
cloud = _cloud_client['healing_hub']
A._cloud_db = lambda: cloud
os.environ['CLOUD_MONGODB_URI'] = 'mongodb://cloud.example'
c = A.app.test_client()
from test_support import arm_csrf
arm_csrf(c)
PASS, FAIL = [], []


def check(label, cond, detail=''):
    (PASS if cond else FAIL).append(label)
    print(('  PASS  ' if cond else '  FAIL  ') + label
          + (('  ->  ' + str(detail)) if detail and not cond else ''))


def login(role='admin', name='Letlotlo Hlaoli'):
    with c.session_transaction() as s:
        s['user'] = {'name': name, 'login': 'a', 'role': role}
        s['last_active'] = datetime.now(timezone.utc).isoformat()


def reset():
    for d in (db, cloud):
        for col in d.list_collection_names():
            d[col].delete_many({})


today = A.local_now().date()

print('\n--- 1. Upload to cloud ---')
reset()
db['medications'].insert_many([{'name': f'Item {i}', 'balance': i, 'price': 1.0} for i in range(3)])
db['sales'].insert_one({'receipt_no': 'S1', 'total': 10.0})
r = A.upload_to_cloud(db, 'Owner')
check('first upload sends every record', r['sent'] == 4, r)
check('the online copy now matches', cloud['medications'].count_documents({}) == 3
      and cloud['sales'].count_documents({}) == 1)
check('the bookkeeping collection stays in the shop', 'sync_hashes' not in cloud.list_collection_names())
check('the online copy knows when it was uploaded', cloud['sync_log'].count_documents({'ok': True}) == 1)
r = A.upload_to_cloud(db, 'Owner')
check('nothing changed: nothing is sent again', r['sent'] == 0, r)
db['medications'].update_one({'name': 'Item 1'}, {'$set': {'balance': 99}})
db['medications'].delete_one({'name': 'Item 2'})
r = A.upload_to_cloud(db, 'Owner')
check('only the changed record is sent', r['sent'] == 1, r)
check('a record deleted in the shop is deleted online', r['removed'] == 1
      and cloud['medications'].count_documents({'name': 'Item 2'}) == 0, r)
check('the change arrived', cloud['medications'].find_one({'name': 'Item 1'})['balance'] == 99)
cloud['medications'].update_one({'name': 'Item 0'}, {'$set': {'balance': -5}})
cloud['medications'].insert_one({'name': 'Typed in online'})
r = A.upload_to_cloud(db, 'Owner')
check('a normal upload does not notice edits made online', r['sent'] == 0)
r = A.upload_to_cloud(db, 'Owner', full=True)
check('a full upload repairs them', cloud['medications'].find_one({'name': 'Item 0'})['balance'] == 0
      and cloud['medications'].count_documents({'name': 'Typed in online'}) == 0, r)
r = A.upload_to_cloud(db, 'Owner')
check('after a full upload, nothing is pending', r['sent'] == 0, r)

print('\n--- 2. The upload button ---')
login()
page = c.get('/owner-reports').get_data(as_text=True)
check('Owner Reports shows the upload button', 'Upload to cloud now' in page)
check('and the time of the last upload', 'Last upload:' in page)
db['sales'].insert_one({'receipt_no': 'S2', 'total': 5.0})
resp = c.post('/owner-reports', data={'send': 'upload'}, follow_redirects=True)
body = resp.get_data(as_text=True)
check('pressing it uploads and says what was sent', 'Uploaded: 1 changed record' in body, body[-600:])
check('the upload is in the audit log', db['audit_log'].count_documents({'target_type': 'cloud_copy'}) == 1)
A._cloud_db = lambda: (_ for _ in ()).throw(RuntimeError('no network'))
resp = c.post('/owner-reports', data={'send': 'upload'}, follow_redirects=True)
check('no network: a clear message, nothing pretended',
      'Upload failed' in resp.get_data(as_text=True)
      and db['sync_log'].count_documents({'ok': False}) == 1)
A._cloud_db = lambda: cloud
login(role='employee', name='Nurse')
n_logs = db['sync_log'].count_documents({})
check('staff cannot upload', c.post('/owner-reports', data={'send': 'upload'}).status_code == 302
      and db['sync_log'].count_documents({}) == n_logs)

print('\n--- 3. Upload reminders on every page ---')
A.SHOP_MODE = True
login()
db['sync_log'].update_many({}, {'$set': {'at': datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)}})
page = c.get('/sales').get_data(as_text=True)
check('an admin in the shop is told when the upload is overdue', 'was last uploaded 5 day(s) ago' in page)
db['sync_log'].insert_one({'at': datetime.now(timezone.utc).replace(tzinfo=None), 'by': 'Owner', 'ok': True, 'sent': 0})
page = c.get('/sales').get_data(as_text=True)
check('no warning after a fresh upload', 'last uploaded' not in page)
login(role='employee', name='Nurse')
db['sync_log'].delete_many({})
page = c.get('/sales').get_data(as_text=True)
check('staff do not see the upload warning', 'Upload to cloud' not in page)
A.SHOP_MODE = False

print('\n--- 4. The online copy is view-only ---')
A.READ_ONLY = True
login()
db['sync_log'].insert_one({'at': datetime.now(timezone.utc).replace(tzinfo=None), 'by': 'Owner', 'ok': True, 'sent': 0})
page = c.get('/sales').get_data(as_text=True)
check('every page says it is the online copy', 'online copy, for viewing only' in page)
before = db['medications'].count_documents({})
resp = c.post('/write-off', data={'med_name': 'Item 0', 'quantity': '1'})
check('a change is refused with an explanation', resp.status_code == 403
      and 'Make the change there' in resp.get_data(as_text=True))
check('nothing changed', db['medications'].count_documents({}) == before
      and db['transactions'].count_documents({'type': 'damage'}) == 0)
check('the owner page has no upload button online', 'Upload to cloud now' not in
      c.get('/owner-reports').get_data(as_text=True))
rr = c.post('/reports', data={'report_type': 'stock_on_hand'})
check('reports can still be run', rr.status_code == 200 and 'online copy, for viewing only' in rr.get_data(as_text=True)
      and 'Nothing was saved' not in rr.get_data(as_text=True), rr.status_code)
check('a refill message cannot be marked online',
      c.post('/refills/whatsapp', data={'receipt_no': 'S1'}).status_code == 403)
os.environ['CRON_SECRET'] = 'cs'
r = c.get('/api/cron/daily', headers={'Authorization': 'Bearer cs'})
check('the evening job does nothing online', 'skipped' in r.get_json())
A.READ_ONLY = False

print('\n--- 5. WhatsApp numbers and links ---')
check('a local number gets 266', A.wa_number('5812 3456') == '26658123456')
check('+266 and 00266 are understood', A.wa_number('+266 5812-3456') == '26658123456'
      and A.wa_number('00266 58123456') == '26658123456')
check('a foreign number is kept', A.wa_number('+27 82 123 4567') == '27821234567')
check('nonsense gives no number', A.wa_number('12') == '' and A.wa_number(None) == '')
link = A.wa_link('58123456', 'Dumela & hello')
check('the link carries the number and the text', link.startswith('https://wa.me/26658123456?text=')
      and unquote(link.split('text=')[1]) == 'Dumela & hello', link)
check('no number: WhatsApp asks who to send to', A.wa_link('', 'x') == 'https://wa.me/?text=x')

print('\n--- 6. Owner messages ---')
reset()
start, _ = A._day_window(today)
db['sales'].insert_one({'receipt_no': 'S1', 'status': 'completed', 'payment_method': 'Cash',
                        'total': 120.0, 'cost_total': 60.0, 'timestamp': start + timedelta(hours=9)})
d = A.daily_summary(db, today)
t = A.whatsapp_daily_text(d)
check('the daily text starts with a bold headline', t.startswith('*Healing Hub') and 'M120.00' in t, t)
check('without a linked website, no "not reached the website" worry', 'website' not in t, t)
w = A.weekly_alerts(db, today)
w['reorder'] = [{'name': f'Drug {i}', 'balance': 1, 'weeks': 0.5, 'supplier': ''} for i in range(15)]
t = A.whatsapp_weekly_text(w, today)
check('long lists are cut short', '…and 5 more' in t and 'Drug 9' in t and 'Drug 10' not in t, t)
os.environ['OWNER_WHATSAPP'] = '58000000'
login()
page = c.get('/owner-reports').get_data(as_text=True)
check('Owner Reports has WhatsApp buttons to the owner',
      'https://wa.me/26658000000?text=' in page and "Send today's summary" in page)
check('email buttons hide when Gmail is not set up', 'Email today' not in page)

print('\n--- 7. Refill calls ---')
reset()


def chronic(receipt, name, phone, sold_on, days, email=None):
    db['sales'].insert_one({'receipt_no': receipt, 'status': 'completed', 'total': 50,
                            'timestamp': datetime.now(timezone.utc).replace(tzinfo=None),
                            'reminder': {'name': name, 'phone': phone, 'email': email,
                                         'days_supply': days, 'sold_on': sold_on.strftime('%Y-%m-%d'),
                                         'status': 'pending'}})


chronic('R1', 'Palesa Mokoena', '58111111', today - timedelta(days=28), 30)    # due in 2 days
chronic('R2', 'Thabo Lebona', '58222222', today - timedelta(days=40), 30)      # 10 days late
chronic('R3', 'Mpho Sello', '58333333', today - timedelta(days=5), 30)         # not due yet
chronic('R4', 'Lineo Ramoso', '58444444', today - timedelta(days=50), 30)      # came back:
chronic('R5', 'Lineo Ramoso', '58444444', today - timedelta(days=1), 30)       # not listed
chronic('R6', 'Kabelo', '', today - timedelta(days=31), 30, email='k@x.com')    # no number
chronic('R7', 'Old Patient', '58777777', today - timedelta(days=200), 30)      # too long ago
rows = A.refill_call_list(db, today)
names = [r['name'] for r in rows]
check('due soon and late patients are listed, most late first',
      names == ['Thabo Lebona', 'Kabelo', 'Palesa Mokoena'], names)
check('someone who already came back is not listed', 'Lineo Ramoso' not in names)
check('a patient with no number is shown for a phone call', not rows[1]['has_whatsapp'])
login(role='employee', name='Nurse Mamotata')
page = c.get('/refills').get_data(as_text=True)
check('staff can open Refill calls', 'Thabo Lebona' in page and '10 day(s) late' in page)
check('it is in the navigation', 'href="/refills"' in page)
resp = c.post('/refills/whatsapp', data={'receipt_no': 'R2'})
loc = resp.headers.get('Location', '')
msg = unquote(loc.split('text=')[1]) if 'text=' in loc else ''
check('WhatsApp opens for that patient', loc.startswith('https://wa.me/26658222222?text='), loc)
check('the message greets them and gives the date', msg.startswith('Dumela Thabo') and 'was due on' in msg, msg)
check('the message never names a medicine or amount', 'tablet' not in msg.lower() and 'M' + '50' not in msg)
rem = db['sales'].find_one({'receipt_no': 'R2'})['reminder']
check('it is marked as messaged, and by whom', rem.get('whatsapp_at') and rem.get('whatsapp_by') == 'Nurse Mamotata')
page = c.get('/refills').get_data(as_text=True)
check('the list shows it was sent', 'by Nurse Mamotata' in page and 'Send again' in page)
msg2 = A.refill_message('Palesa Mokoena', today + timedelta(days=2), 2)
check('due soon: a gentle reminder', 'your next refill is due on' in msg2)
resp = c.post('/refills/whatsapp', data={'receipt_no': 'R6'}, follow_redirects=True)
check('no number: told to phone instead', 'Phone them instead' in resp.get_data(as_text=True))

print('\n--- 8. Selling in the shop does not wait for the network ---')
A.SHOP_MODE = True
sale = {'_id': 1, 'receipt_no': 'X', 'reminder': {'sold_on': today.strftime('%Y-%m-%d'), 'days_supply': 30}}
note = A._reminder_saved_note(sale)
check('the cashier is told where the reminder went', 'Refill calls' in note, note)
A.SHOP_MODE = False

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
if FAIL:
    raise SystemExit(1)
