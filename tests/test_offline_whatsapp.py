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

print('\n--- 1. Upload: the shop stays in charge ---')
reset()
A.SHOP_MODE = True
db['medications'].insert_many([{'name': f'Item {i}', 'balance': i, 'price': 1.0} for i in range(3)])
db['sales'].insert_one({'receipt_no': 'S1', 'total': 10.0})
r = A.upload_to_cloud(db, 'Owner')
check('first upload sends every record', r['sent'] == 4, r)
check('the online copy now matches', cloud['medications'].count_documents({}) == 3
      and cloud['sales'].count_documents({}) == 1)
check('the bookkeeping stays in the shop', 'sync_hashes' not in cloud.list_collection_names())
check('both copies agree the shop is in charge',
      A.baton_holder(db) == 'shop' and A.baton_holder(cloud) == 'shop')
r = A.upload_to_cloud(db, 'Owner')
check('nothing changed: nothing is sent again', r['sent'] == 0 and r['received'] == 0, r)
db['medications'].update_one({'name': 'Item 1'}, {'$set': {'balance': 99}})
db['medications'].delete_one({'name': 'Item 2'})
r = A.upload_to_cloud(db, 'Owner')
check('only the changed record is sent', r['sent'] == 1, r)
check('a record deleted in the shop is deleted online',
      cloud['medications'].count_documents({'name': 'Item 2'}) == 0, r)
cloud['medications'].update_one({'name': 'Item 0'}, {'$set': {'balance': -5}})
r = A.upload_to_cloud(db, 'Owner')
check('while the shop is in charge, online is not read back', r['received'] == 0)
r = A.upload_to_cloud(db, 'Owner', full=True)
check('a full upload repairs the online copy', cloud['medications'].find_one({'name': 'Item 0'})['balance'] == 0, r)

print('\n--- 2. Hand over to online, work online, bring back ---')
r = A.sync_with_cloud(db, 'Owner', hand_to='online')
check('handing over puts online in charge on both sides',
      A.baton_holder(db) == 'online' and A.baton_holder(cloud) == 'online')
login()
resp = c.post('/write-off', data={'med_name': 'Item 0', 'quantity': '1'})
check('the shop is now view-only, and says how to get control back',
      resp.status_code == 403 and 'Bring back to shop' in resp.get_data(as_text=True))
page = c.get('/sales').get_data(as_text=True)
check('every shop page says online is in charge', 'Online is in charge' in page)
check('Owner Reports offers Bring back to shop', 'value="takeback"' in c.get('/owner-reports').get_data(as_text=True))
# Online, working away from the shop
A.SHOP_MODE = False
A.get_mongo_client = lambda: _cloud_client
check('the online copy accepts changes while in charge', not A.read_only_now())
cloud['sales'].insert_one({'receipt_no': 'S9', 'total': 77.0})
cloud['medications'].update_one({'name': 'Item 1'}, {'$set': {'balance': 50}})
cloud['medications'].delete_one({'name': 'Item 0'})
cloud['audit_log'].insert_one({'action': 'CREATE', 'target_id': 'S9'})
page = c.get('/sales').get_data(as_text=True)
check('online pages say online is in charge', 'Online is in charge since' in page)
A.SHOP_MODE = True
A.get_mongo_client = lambda _client=_f: _client
resp = c.post('/owner-reports', data={'send': 'takeback'}, follow_redirects=True)
body = resp.get_data(as_text=True)
check('Bring back to shop reports what came down', 'Back in the shop' in body and 'received' in body,
      body[body.find('Back in'):body.find('Back in') + 200])
check('the online sale is now in the shop', db['sales'].count_documents({'receipt_no': 'S9'}) == 1)
check('the online stock change is in the shop', db['medications'].find_one({'name': 'Item 1'})['balance'] == 50)
check('a record deleted online is deleted in the shop', db['medications'].count_documents({'name': 'Item 0'}) == 0)
check('new log entries came down too', db['audit_log'].count_documents({'target_id': 'S9'}) == 1)
check('the shop is in charge again', A.baton_holder(db) == 'shop' and A.baton_holder(cloud) == 'shop')
check('and can make changes again', not A.read_only_now())
r = A.upload_to_cloud(db, 'Owner')
check('the next upload sends only the audit note of the take-back', r['sent'] == 1 and r['received'] == 0, r)
r = A.upload_to_cloud(db, 'Owner')
check('after the round trip nothing is left to move', r['sent'] == 0 and r['received'] == 0, r)

print('\n--- 3. Emergency, and records changed in both places ---')
A.sync_with_cloud(db, 'Owner', hand_to='online')
cloud['medications'].update_one({'name': 'Item 1'}, {'$set': {'balance': 40}})   # online sold some
cloud['sales'].insert_one({'receipt_no': 'S10', 'total': 5.0})
login()
resp = c.post('/owner-reports', data={'send': 'emergency'}, follow_redirects=True)
check('the emergency needs a tick to confirm', 'Tick the box' in resp.get_data(as_text=True)
      and A.baton_holder(db) == 'online')
c.post('/owner-reports', data={'send': 'emergency', 'confirm': '1'})
check('the shop takes charge without the network', A.baton_holder(db) == 'shop' and A.read_only_now() is False)
db['medications'].update_one({'name': 'Item 1'}, {'$set': {'balance': 45}})       # shop sold some too
db['sales'].insert_one({'receipt_no': 'S11', 'total': 6.0})
r = A.upload_to_cloud(db, 'Owner')
check('the record changed in both places is listed', r['conflict_count'] == 1
      and 'Item 1' in r['conflicts'][0], r['conflicts'])
check("the shop's version is kept in both copies",
      db['medications'].find_one({'name': 'Item 1'})['balance'] == 45
      and cloud['medications'].find_one({'name': 'Item 1'})['balance'] == 45)
check('sales made in each place are all kept', db['sales'].count_documents({'receipt_no': {'$in': ['S10', 'S11']}}) == 2
      and cloud['sales'].count_documents({'receipt_no': {'$in': ['S10', 'S11']}}) == 2)
page = c.get('/owner-reports').get_data(as_text=True)
check('Owner Reports lists it for checking', 'changed both in the' in page and 'medications: Item 1' in page)
# Online takes charge in an emergency while the shop holds it (shop computer broken)
A.SHOP_MODE = False
A.get_mongo_client = lambda: _cloud_client
check('online is view-only while the shop is in charge', A.read_only_now())
A.emergency_take_control(cloud, 'Owner')
check('online can take charge in an emergency', not A.read_only_now())
cloud['sales'].insert_one({'receipt_no': 'S12', 'total': 8.0})
A.SHOP_MODE = True
A.get_mongo_client = lambda _client=_f: _client
r = A.upload_to_cloud(db, 'Owner')
check('the next shop sync brings the online work down', db['sales'].count_documents({'receipt_no': 'S12'}) == 1
      and A.baton_holder(cloud) == 'shop', r)
A.sync_with_cloud(db, 'Owner', hand_to='online')
try:
    A.sync_with_cloud(db, 'Owner', hand_to='shop', full=True)
    refused = False
except RuntimeError:
    refused = True
check('a full upload is refused while online is in charge', refused)
A.sync_with_cloud(db, 'Owner', hand_to='shop')

print('\n--- 4. Buttons, messages and warnings ---')
login()
page = c.get('/owner-reports').get_data(as_text=True)
check('the shop is offered upload and hand-over', 'value="upload"' in page and 'value="handover"' in page)
db['medications'].insert_one({'name': 'New item', 'balance': 1, 'price': 1.0})
resp = c.post('/owner-reports', data={'send': 'upload'}, follow_redirects=True)
check('pressing Upload says what was sent', 'Uploaded: 1 record(s) sent' in resp.get_data(as_text=True))
check('the sync is in the audit log', db['audit_log'].count_documents({'target_type': 'cloud_copy'}) >= 1)
A._cloud_db = lambda: (_ for _ in ()).throw(RuntimeError('no network'))
resp = c.post('/owner-reports', data={'send': 'handover'}, follow_redirects=True)
check('no network: a clear message, and control does not change hands',
      'nothing changed hands' in resp.get_data(as_text=True) and A.baton_holder(db) == 'shop')
A._cloud_db = lambda: cloud
login(role='employee', name='Nurse')
n_logs = db['sync_log'].count_documents({})
check('staff cannot sync', c.post('/owner-reports', data={'send': 'upload'}).status_code == 302
      and db['sync_log'].count_documents({}) == n_logs)
login()
db['sync_log'].update_many({}, {'$set': {'at': datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)}})
check('an admin in the shop is told when a sync is overdue',
      'was last synced 5 day(s) ago' in c.get('/sales').get_data(as_text=True))
login(role='employee', name='Nurse')
check('staff do not see that warning', 'last synced' not in c.get('/sales').get_data(as_text=True))
login()
A.SHOP_MODE = False
A.get_mongo_client = lambda: _cloud_client
page = c.get('/sales').get_data(as_text=True)
check('online, while the shop is in charge, pages say view-only', 'this online copy is view-only' in page)
resp = c.post('/write-off', data={'med_name': 'Item 1', 'quantity': '1'})
check('and changes are refused, pointing to the hand-over', resp.status_code == 403
      and 'Upload and hand over to online' in resp.get_data(as_text=True))
rr = c.post('/reports', data={'report_type': 'stock_on_hand'})
check('reports can still be run', rr.status_code == 200, rr.status_code)
check('a refill message cannot be marked', c.post('/refills/whatsapp', data={'receipt_no': 'S1'}).status_code == 403)
os.environ['CRON_SECRET'] = 'cs'
r = c.get('/api/cron/daily', headers={'Authorization': 'Bearer cs'})
check('the evening job does nothing on a view-only copy', 'skipped' in r.get_json())
A.SHOP_MODE = False
A.get_mongo_client = lambda _client=_f: _client
db['sync_control'].delete_many({})

print('\n--- 4b. Duplicate usernames ---')
login()
db['users'].insert_many([{'username': 'dup', 'role': 'admin'}, {'username': 'dup', 'role': 'admin'},
                         {'username': 'one', 'role': 'employee'}])
check('duplicate usernames are found', A.duplicate_usernames(db) == ['dup'], A.duplicate_usernames(db))
check('Owner Reports warns about them', 'share the username dup' in c.get('/owner-reports').get_data(as_text=True))
db['users'].delete_many({'username': {'$in': ['dup', 'one']}})
check('no warning once fixed', 'share the username' not in c.get('/owner-reports').get_data(as_text=True))

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
