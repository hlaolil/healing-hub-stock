"""Owner reports: daily summary, weekly alerts, refill adherence, supplier prices, cron."""
from _root import ROOT  # the app folder, one up from tests/
import os
os.environ['SECRET_KEY'] = 'k'
import mongomock, pymongo
from datetime import datetime, timezone, timedelta

_f = mongomock.MongoClient()
pymongo.MongoClient = lambda *a, **k: _f
import app as A
A.get_mongo_client = lambda _client=_f: _client
A.init_db_collections()
db = _f['healing_hub']
meds, txs, sales = db['medications'], db['transactions'], db['sales']
c = A.app.test_client()
from test_support import arm_csrf
arm_csrf(c)
PASS, FAIL = [], []


def check(label, cond, detail=''):
    (PASS if cond else FAIL).append(label)
    print(('  PASS  ' if cond else '  FAIL  ') + label
          + (('  ->  ' + detail) if detail and not cond else ''))


def login(role='admin', name='Letlotlo Hlaoli'):
    with c.session_transaction() as s:
        s['user'] = {'name': name, 'login': 'a', 'role': role}
        s['last_active'] = datetime.now(timezone.utc).isoformat()


def reset():
    for col in db.list_collection_names():
        db[col].delete_many({})


# Emails are captured instead of sent.
sent = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        if pw != 'abcdefghijklmnop':
            raise A.smtplib.SMTPAuthenticationError(535, b'Username and Password not accepted')

    def send_message(self, msg):
        sent.append(msg)


A.smtplib.SMTP_SSL = FakeSMTP
now = datetime.utcnow()
today = A.local_now().date()

print('\n--- 1. Refill adherence ---')
reset()


def chronic_sale(contact, sold_on, days, status='sent'):
    sales.insert_one({'receipt_no': f'R{sales.count_documents({})}', 'status': 'completed',
                      'timestamp': now, 'total': 10, 'cost_total': 5,
                      'reminder': {**contact, 'name': 'P', 'days_supply': days,
                                   'sold_on': sold_on.strftime('%Y-%m-%d'), 'status': status}})


d0 = today - timedelta(days=100)
# Patient A: back on time twice (day 30 and day 62), then still within their supply.
chronic_sale({'email': 'a@x.com'}, d0, 30)
chronic_sale({'email': 'A@X.com'}, d0 + timedelta(days=30), 30)
chronic_sale({'email': 'a@x.com'}, d0 + timedelta(days=62), 60)
# Patient B (phone only): came back 20 days late.
chronic_sale({'phone': '(+266) 5812 3456'}, d0, 30)
chronic_sale({'phone': '58123456'}, d0 + timedelta(days=50), 90)
# Patient C: never came back.
chronic_sale({'email': 'c@x.com'}, d0, 30)
a = A.refill_adherence(db, today)
check('three patients, matched by email (any case) or phone digits', a['patients'] == 3, str(a))
check('on time counts returns within a week of running out', a['on_time'] == 2, str(a))
check('a return weeks after running out is late', a['late'] == 1, str(a))
check('no return after the grace period is missed', a['missed'] == 1, str(a))
check('a supply not yet run out is not counted', a['due'] == 4, str(a))
check('the rate is on time / due', abs(a['rate'] - 0.5) < 1e-9, str(a['rate']))

print('\n--- 2. Daily summary ---')
reset()
start, _end = A._day_window(today)
sales.insert_many([
    {'receipt_no': 'S1', 'status': 'completed', 'payment_method': 'Cash', 'total': 100.0,
     'cost_total': 60.0, 'timestamp': start + timedelta(hours=10),
     'reminder': {'email': 'a@x.com', 'days_supply': 30, 'sold_on': str(today), 'status': 'sent'}},
    {'receipt_no': 'S2', 'status': 'completed', 'payment_method': 'M-Pesa', 'total': 50.0,
     'cost_total': 20.0, 'timestamp': start + timedelta(hours=11)},
    {'receipt_no': 'S3', 'status': 'voided', 'payment_method': 'Cash', 'total': 30.0, 'cost_total': 10,
     'timestamp': start + timedelta(hours=12), 'voided_at': start + timedelta(hours=13),
     'voided_by': 'Admin', 'void_reason': 'rung twice'},
    {'receipt_no': 'S4', 'status': 'completed', 'payment_method': 'Cash', 'total': 999.0,
     'cost_total': 1, 'timestamp': start - timedelta(hours=2)},
    {'receipt_no': 'S5', 'status': 'completed', 'payment_method': 'Cash', 'total': 5.0, 'cost_total': 1,
     'timestamp': start - timedelta(days=1),
     'late_entry': {'paper_receipt_no': 'P1', 'entered_at': start + timedelta(hours=9),
                    'entered_by': 'Nurse', 'approved': False}},
])
txs.insert_one({'type': 'damage', 'med_name': 'Insulin', 'quantity': -2, 'line_value': -180.0,
                'reason': 'Cold chain failure', 'user': 'Nurse', 'timestamp': start + timedelta(hours=8)})
txs.insert_one({'type': 'unmet_demand', 'med_name': 'Metformin', 'shortfall': 30,
                'timestamp': start + timedelta(hours=9)})
d = A.daily_summary(db, today)
check("counts only today's completed sales", d['count'] == 2 and d['total'] == 150.0, str(d['total']))
check('gross profit is total minus cost', d['profit'] == 70.0)
check('split by payment method', dict(d['by_method'])['M-Pesa']['total'] == 50.0)
check('voids today are listed with reason', d['voids'] and d['voids'][0]['reason'] == 'rung twice')
check('write-offs today are listed with value', d['writeoffs'] and d['writeoffs'][0]['value'] == 180.0)
check('paper receipts entered today are counted', d['late_today'] == 1 and d['awaiting'] == 1)
check('unmet demand is listed', d['unmet'] and d['unmet'][0]['name'] == 'Metformin')
check('no temperature places in use: nothing reported missing', d['missing_temps'] == [])
day0 = datetime(today.year, today.month, today.day)
db['temperature_logs'].insert_many([
    {'location': 'Fridge', 'session': 'Morning', 'date': day0 - timedelta(days=1)},
    {'location': 'Dispensary', 'session': 'Morning', 'date': day0},
])
d = A.daily_summary(db, today)
check('missing readings are listed only for places in use',
      sorted(d['missing_temps']) == ['Dispensary (Afternoon)', 'Fridge (Afternoon)', 'Fridge (Morning)'],
      str(d['missing_temps']))
check('reminders set today are counted', d['reminders_set'] == 1)
subject, text, html = A.render_daily_email(d)
check('the subject gives the day total', 'M150.00' in subject and '2 sale' in subject, subject)
check('the email flags the void and the write-off', 'rung twice' in text and 'Cold chain failure' in text)
check('the HTML version is escaped', '<script' not in html)

print('\n--- 3. Weekly alerts ---')
reset()
soon = (today + timedelta(days=30)).strftime('%Y-%m-%d')
later = (today + timedelta(days=400)).strftime('%Y-%m-%d')
meds.insert_many([
    {'name': 'Metformin 500mg', 'balance': 20, 'price': 0.5, 'selling_price': 0.9, 'expiry_date': later,
     'supplier': 'Medisupply'},
    {'name': 'Cough syrup', 'balance': 10, 'price': 30.0, 'selling_price': 25.0, 'expiry_date': soon},
    {'name': 'Plenty', 'balance': 1000, 'price': 1.0, 'selling_price': 2.0, 'expiry_date': later},
])
for i in range(6):   # 180 Metformin dispensed over the last 90 days: 60 a month
    txs.insert_one({'type': 'dispense', 'med_name': 'Metformin 500mg', 'quantity': 30,
                    'timestamp': now - timedelta(days=10 * i + 1)})
txs.insert_one({'type': 'dispense', 'med_name': 'Plenty', 'quantity': 30, 'timestamp': now - timedelta(days=5)})
w = A.weekly_alerts(db, today)
check('an item with under a month left is flagged to reorder',
      [r['name'] for r in w['reorder']] == ['Metformin 500mg'], str(w['reorder']))
check('with weeks left and the last supplier', w['reorder'][0]['weeks'] < 2 and w['reorder'][0]['supplier'] == 'Medisupply')
check('stock expiring within 90 days is flagged with its value',
      [e['name'] for e in w['expiring']] == ['Cough syrup'] and w['expiring'][0]['value'] == 300.0)
check('an item priced below cost is flagged with a suggested price',
      w['below_cost'] and w['below_cost'][0]['name'] == 'Cough syrup'
      and w['below_cost'][0]['suggested'] == A.suggested_price(30.0))
subject, text, html = A.render_weekly_email(w, today)
check('the weekly subject counts each list', '1 to reorder' in subject and '1 expiring' in subject, subject)

print('\n--- 4. Supplier prices ---')
reset()
for sup, unit, days in [('Medisupply', 0.50, 40), ('Pharmaco', 0.40, 20), ('Medisupply', 0.55, 5)]:
    txs.insert_one({'type': 'receive', 'med_name': 'Metformin 500mg', 'supplier': sup, 'price': unit,
                    'pack_price': unit * 100, 'pack_size': 100, 'timestamp': now - timedelta(days=days)})
txs.insert_one({'type': 'receive', 'med_name': 'Plenty', 'supplier': 'Medisupply', 'price': 1.0,
                'timestamp': now})
rows = A.supplier_prices(db)
met = rows[0]
check('items with a price difference come first', met['name'] == 'Metformin 500mg')
check("each supplier's latest price is used", [o['unit'] for o in met['offers']] == [0.40, 0.55], str(met['offers']))
check('the cheapest supplier is first', met['offers'][0]['supplier'] == 'Pharmaco')
check('the saving is worked out', met['saving'] == 27, str(met['saving']))

print('\n--- 5. Emails and the daily job ---')
reset()
for k in ('GMAIL_USER', 'GMAIL_APP_PASSWORD', 'OWNER_EMAIL', 'CRON_SECRET'):
    os.environ.pop(k, None)
check('without Gmail settings nothing is sent', A.send_owner_email('s', 't', 'h') is False and not sent)
os.environ['GMAIL_USER'] = 'healinghub@gmail.com'
os.environ['GMAIL_APP_PASSWORD'] = 'abcd efgh ijkl mnop'
check('the app password works with its spaces', A.send_owner_email('s', 't', '<p>h</p>') is True)
check('it goes to the Gmail account by default', sent[-1]['To'] == 'healinghub@gmail.com')
os.environ['OWNER_EMAIL'] = 'owner@example.com'
A.send_owner_email('s', 't', 'h')
check('or to OWNER_EMAIL when set', sent[-1]['To'] == 'owner@example.com')
os.environ['GMAIL_APP_PASSWORD'] = 'wrongwrongwrong1'
check('a wrong app password returns False instead of crashing', A.send_owner_email('s', 't', 'h') is False)
os.environ['GMAIL_APP_PASSWORD'] = 'abcdefghijklmnop'

r = c.get('/api/cron/daily')
check('the daily job needs CRON_SECRET to be set', r.status_code == 401)
os.environ['CRON_SECRET'] = 'cron-secret'
r = c.get('/api/cron/daily', headers={'Authorization': 'Bearer nope'})
check('and refuses the wrong secret', r.status_code == 401)
sent.clear()
calls = []


class _Resp:
    status_code = 200


A.requests.post = lambda url, **kw: (calls.append(kw['json']), _Resp())[1]
os.environ['WEBSITE_URL'] = 'https://site.example'
os.environ['TILL_SYNC_SECRET'] = 'x'
sales.insert_one({'receipt_no': 'R1', 'status': 'completed', 'timestamp': now, 'total': 1,
                  'reminder': {'name': 'P', 'email': 'p@x.com', 'phone': '', 'days_supply': 30,
                               'sold_on': str(today), 'status': 'pending', 'attempts': 1}})
os.environ['WEEKLY_ALERT_DAY'] = A.WEEKDAYS[today.weekday()]
r = c.get('/api/cron/daily', headers={'Authorization': 'Bearer cron-secret'})
body = r.get_json()
check('with the secret it runs', r.status_code == 200 and body['daily_email'] is True, str(body))
check('pending refill reminders are retried', body['reminders_retried'] == 1 and len(calls) == 1
      and sales.find_one({'receipt_no': 'R1'})['reminder']['status'] == 'sent')
check('on the weekly day the alerts go too', body['weekly_email'] is True and len(sent) == 2)
os.environ['WEEKLY_ALERT_DAY'] = A.WEEKDAYS[(today.weekday() + 1) % 7]
sent.clear()
body = c.get('/api/cron/daily', headers={'Authorization': 'Bearer cron-secret'}).get_json()
check('on other days only the summary', body['weekly_email'] is None and len(sent) == 1)

print('\n--- 6. The Owner Reports page ---')
login(role='employee', name='Cashier')
r = c.get('/owner-reports')
check('a cashier cannot open it', r.status_code == 302)
login()
r = c.get('/owner-reports')
page = r.get_data(as_text=True)
check('an admin can', r.status_code == 200 and 'Refill adherence' in page and 'Supplier prices' in page)
sent.clear()
c.post('/owner-reports', data={'send': 'daily'})
check("'Email today's summary now' sends it", len(sent) == 1)
check('the nav shows Owner Reports to admins', 'Owner Reports' in c.get('/sell').get_data(as_text=True))

print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
