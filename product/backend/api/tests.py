import csv
import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, RequestFactory
from .models import User, Query, ImportBatch, ExportRecord, Mutation, AuthAttempt
from .services import idempotent, manual_query, ApiProblem

PASSWORD = 'Maple-River-Cobalt-7281'
NOTICE = ['publish_date','procedure_id','lot_id','start_price','reqnum','procedure_name','subject','is_smp','customer_inn','customer_kpp','is_eshop_or_aisgz']
ITEM = ['lot_id','product_name','okpd2_code']

def csv_text(header, rows, delimiter=';'):
    out = io.StringIO(newline='')
    writer = csv.writer(out, delimiter=delimiter)
    writer.writerow(header)
    writer.writerows(rows)
    return '\ufeff' + out.getvalue()

def pair(subject='Испытание оборудования', items=None, delimiter=';'):
    return {'notices': csv_text(NOTICE, [['2026-10-02','0002','0001','100.00','001','Запрос',subject,'false','0012345678','','АИС ГЗ']], delimiter),
            'items': csv_text(ITEM, items or [['0001','Прибор "А"; два\nряда','26.20.11.110'],['0001','Прибор "А"; два\nряда','26.20.11.110']], delimiter), 'files': ['Закупки.csv','ТРУ.csv']}

def token(client):
    return client.get('/api/v1/auth/csrf').json()['csrfToken']

def send(client, path, data=None, method='POST', key=None, origin=None):
    headers = {'HTTP_X_CSRFTOKEN': token(client)}
    if key:
        headers['HTTP_IDEMPOTENCY_KEY'] = key
    if origin:
        headers['HTTP_ORIGIN'] = origin
    return getattr(client, method.lower())('/api/v1/' + path, data=json.dumps(data or {}, ensure_ascii=False), content_type='application/json', **headers)

class ApiTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user('a@example.test', PASSWORD, name='Алиса')
        self.b = User.objects.create_user('b@example.test', PASSWORD, name='Борис')
        self.ca = Client(enforce_csrf_checks=True)
        self.cb = Client(enforce_csrf_checks=True)
        self.ca.force_login(self.a)
        self.cb.force_login(self.b)
    def imported(self, data=None):
        response = send(self.ca, 'imports', data or pair(), key=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()
    def test_auth_csrf_register_login_logout_cookie_flags(self):
        c = Client(enforce_csrf_checks=True)
        data = {'email':'NEW@Example.test','name':'Новый','password':PASSWORD}
        denied = c.post('/api/v1/auth/register', data=json.dumps(data), content_type='application/json')
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()['error']['code'], 'CSRF_REJECTED')
        response = send(c, 'auth/register', data)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['user']['email'], 'new@example.test')
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie['httponly']); self.assertEqual(cookie['samesite'], 'Lax')
        user = User.objects.get(email='new@example.test')
        self.assertTrue(user.password.startswith('pbkdf2_sha256$')); self.assertNotEqual(user.password, PASSWORD)
        old_key = c.session.session_key
        self.assertEqual(send(c, 'auth/logout').status_code, 200)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertEqual(c.get('/api/v1/auth/me').status_code, 401)
        self.assertEqual(send(c, 'auth/login', {'email':'NEW@example.test','password':PASSWORD}).status_code, 200)
    def test_origin_rejection_and_headers(self):
        response = send(self.ca, 'auth/profile', {'name':'Changed'}, method='PATCH', origin='https://evil.test')
        self.assertEqual(response.status_code, 403)
        health = self.ca.get('/api/v1/health')
        self.assertEqual(health['X-Frame-Options'], 'DENY')
        self.assertEqual(health['Cache-Control'], 'no-store')
        self.assertNotIn('unsafe-eval', health['Content-Security-Policy'])
        self.assertEqual(Client().get('/api/v1/health', HTTP_HOST='evil.test').status_code, 400)
    def test_anonymous_resource_protection(self):
        c = Client(enforce_csrf_checks=True)
        for path in ['queries','analytics','companies','imports/'+str(uuid.uuid4()),'queries/'+str(uuid.uuid4())]:
            self.assertEqual(c.get('/api/v1/'+path).status_code, 401, path)
        for path in ['imports','queries','exports','source-jobs']:
            self.assertEqual(send(c,path,{}).status_code, 401, path)
    def test_import_retains_raw_leading_zero_newline_and_duplicates(self):
        value = self.imported()
        self.assertEqual(value['rows'], {'notices':1,'items':2})
        self.assertIn('DUPLICATE_ITEMS', [x['code'] for x in value['issues']])
        q = self.ca.get('/api/v1/queries/'+value['queryIds'][0]).json()
        self.assertEqual(q['rawNotice']['customer_inn'], '0012345678')
        self.assertEqual(q['procurement']['lotId'], '0001')
        self.assertEqual(q['rawItems'][0]['product_name'], 'Прибор "А"; два\nряда')
        self.assertNotEqual(q['procurement']['items'][0]['id'], q['procurement']['items'][1]['id'])
        self.assertEqual(q['status'], 'awaiting_engine'); self.assertEqual(q['recommendations'], [])
    def test_csv_comma_and_missing_item_warning(self):
        value = self.imported(pair(delimiter=','))
        self.assertEqual(value['rows']['items'],2)
        p = pair(); p['items'] = csv_text(ITEM, [])
        value = self.imported(p)
        self.assertIn('NO_ITEMS', [x['code'] for x in value['issues']])
    def test_multipart_and_encoding_boundary(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        p = pair()
        response = self.ca.post('/api/v1/imports', {'notices':SimpleUploadedFile('n.csv',p['notices'].encode()),'items':SimpleUploadedFile('i.csv',p['items'].encode())}, HTTP_X_CSRFTOKEN=token(self.ca),HTTP_IDEMPOTENCY_KEY='multipart-key')
        self.assertEqual(response.status_code,201,response.content)
        response = self.ca.post('/api/v1/imports', {'notices':SimpleUploadedFile('n.csv',b'\xff'),'items':SimpleUploadedFile('i.csv',p['items'].encode())}, HTTP_X_CSRFTOKEN=token(self.ca),HTTP_IDEMPOTENCY_KEY='multipart-bad')
        self.assertEqual(response.status_code,422)
    def test_atomic_invalid_import_and_limits(self):
        for mutate in [lambda p:p.update(items=csv_text(ITEM,[['999','wrong','']])), lambda p:p.update(notices=p['notices']+p['notices'].splitlines()[1]+'\n'), lambda p:p.update(notices=p['notices'].replace('2026-10-02','2026-13-44')),lambda p:p.update(items=p['items'].replace('okpd2_code','wrong_code'))]:
            data=pair();mutate(data)
            response=send(self.ca,'imports',data,key=str(uuid.uuid4()))
            self.assertEqual(response.status_code,422,response.content)
            self.assertNotIn('/var/',response.json()['error']['message'])
        self.assertEqual(ImportBatch.objects.count(),0);self.assertEqual(Query.objects.count(),0);self.assertEqual(Mutation.objects.count(),0)
        data=pair(items=[['0001','x','']]*10001)
        self.assertEqual(send(self.ca,'imports',data,key='too-many-items').status_code,413)
    def test_idempotency_replay_conflict_and_owner_namespace(self):
        data=pair();key='same-key-12345'
        first=send(self.ca,'imports',data,key=key); second=send(self.ca,'imports',data,key=key)
        self.assertEqual(first.json(),second.json());self.assertEqual(ImportBatch.objects.count(),1)
        self.assertEqual(send(self.ca,'imports',pair('changed'),key=key).status_code,409)
        self.assertEqual(send(self.cb,'imports',data,key=key).status_code,201)
        self.assertEqual(ImportBatch.objects.count(),2)
        self.assertEqual(send(self.ca,'imports',data).status_code,400)
    def test_two_account_resource_isolation(self):
        value=self.imported();qid=value['queryIds'][0];iid=value['id']
        for path in [f'queries/{qid}',f'imports/{iid}']:
            self.assertEqual(self.cb.get('/api/v1/'+path).status_code,404)
        for path,method,data in [(f'queries/{qid}/saved','PATCH',{'saved':True}),(f'queries/{qid}/start','POST',{}),(f'imports/{iid}/start','POST',{}),('source-jobs','POST',{'queryId':qid}),('exports','POST',{'queryId':qid,'format':'json','resultVersion':'input-v1'}),('exports/confirm','POST',{'queryId':qid,'format':'json'})]:
            self.assertEqual(send(self.cb,path,data,method=method,key=str(uuid.uuid4())).status_code,404,path)
        self.assertEqual(self.cb.get('/api/v1/queries').json(),[])
        self.assertEqual(self.cb.get('/api/v1/analytics').json()['items'],0)
    def test_statistics_and_durable_start_are_owned(self):
        self.assertEqual(self.ca.get('/api/v1/analytics').json()['notices'],0)
        value=self.imported();qid=value['queryIds'][0]
        stats=self.ca.get('/api/v1/analytics').json()
        self.assertEqual((stats['notices'],stats['items'],stats['codes'],stats['inn']),(1,2,1,0))
        self.assertEqual(stats['withSuppliers'],0)
        self.assertEqual(self.ca.get('/api/v1/companies').json(),[])
        self.assertEqual(send(self.ca,f'queries/{qid}/start').json()['status'],'queued')
        self.assertEqual(send(self.ca,f'imports/{value["id"]}/start').status_code,202)
        self.assertEqual(send(self.ca,'source-jobs',{'queryId':qid}).status_code,409)
    def test_saved_and_manual_validation(self):
        data={'draft':{'mode':'text','text':'<script>alert(1)</script>','codes':[],'region':'','price':''}}
        response=send(self.ca,'queries',data,key='manual-query-key')
        self.assertEqual(response.status_code,201,response.content)
        q=response.json();self.assertEqual(q['procurement']['subject'],'<script>alert(1)</script>')
        for _ in range(2):
            self.assertEqual(send(self.ca,'queries/'+q['id']+'/saved',{'saved':True},method='PATCH').status_code,200)
        self.assertEqual(self.ca.get('/api/v1/analytics').json()['saved'],1)
        self.assertEqual(send(self.ca,'queries/'+q['id']+'/saved',{'saved':'false'},method='PATCH').status_code,422)
        self.assertEqual(send(self.ca,'queries',{'draft':{'mode':'text','text':'','codes':[]}},key='empty-draft-key').status_code,422)
    def test_export_owned_raw_input_formula_safe_and_idempotent(self):
        value=self.imported(pair(' =1+1',items=[['0001','@SUM(1,2)','01.01']]))
        qid=value['queryIds'][0]
        body={'queryId':qid,'companyIds':[],'resultVersion':'input-v1','format':'csv'}
        response=send(self.ca,'exports',body,key='export-key-123')
        self.assertEqual(response.status_code,200,response.content)
        rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(rows[1][7],"' =1+1");self.assertEqual(rows[1][-3],"'@SUM(1,2)")
        self.assertEqual(send(self.ca,'exports',body,key='export-key-123').content,response.content)
        self.assertEqual(ExportRecord.objects.count(),1)
        self.assertEqual(send(self.ca,'exports/confirm',{'queryId':qid,'format':'csv'}).status_code,200)
        body['format']='json'; exported=send(self.ca,'exports',body,key='export-json-key')
        self.assertEqual(exported.json()['query']['rawNotice']['subject'],' =1+1')
        body['format']='pdf';response=send(self.ca,'exports',body,key='export-pdf-key')
        self.assertEqual(response.status_code,200,response.content);self.assertTrue(response.content.startswith(b'%PDF-'))
    def test_password_change_revokes_other_sessions_preserves_current(self):
        other=Client(enforce_csrf_checks=True);other.force_login(self.a)
        new='Silver-Dawn-Copper-9542'
        self.assertEqual(send(self.ca,'auth/password',{'currentPassword':'wrong','newPassword':new}).status_code,422)
        old_key=self.ca.session.session_key
        self.assertEqual(send(self.ca,'auth/password',{'currentPassword':PASSWORD,'newPassword':new}).status_code,200)
        self.assertNotEqual(self.ca.session.session_key,old_key)
        self.assertEqual(self.ca.get('/api/v1/auth/me').status_code,200)
        self.assertEqual(other.get('/api/v1/auth/me').status_code,401)
        self.assertEqual(send(other,'auth/login',{'email':self.a.email,'password':PASSWORD}).status_code,401)
        self.assertEqual(send(other,'auth/login',{'email':self.a.email,'password':new}).status_code,200)
    def test_auth_throttling_survives_clients_and_does_not_store_email(self):
        for _ in range(10):
            c=Client(enforce_csrf_checks=True)
            self.assertEqual(send(c,'auth/login',{'email':'none@example.test','password':PASSWORD}).status_code,401)
        self.assertEqual(send(Client(enforce_csrf_checks=True),'auth/login',{'email':'none@example.test','password':PASSWORD}).status_code,429)
        self.assertTrue(all(len(x.key)==40 and '@' not in x.key for x in AuthAttempt.objects.all()))
    def test_invalid_json_unknown_fields_and_routes(self):
        response=self.ca.post('/api/v1/queries',data='{',content_type='application/json',HTTP_X_CSRFTOKEN=token(self.ca))
        self.assertEqual(response.status_code,400)
        self.assertEqual(send(self.ca,'auth/profile',{'name':'x','is_staff':True},method='PATCH').status_code,422)
        self.assertEqual(self.ca.get('/api/v1/queries/not-a-uuid').status_code,404)
        self.assertEqual(self.ca.get('/api/v1/does-not-exist').status_code,404)
        self.assertEqual(self.ca.get('/api/v1/auth/login').status_code,405)

class ConcurrencyTests(TransactionTestCase):
    def test_distinct_concurrent_keys_do_not_bypass_account_quota(self):
        user=User.objects.create_user('quota@example.test',PASSWORD,name='Квота')
        def run(index):
            close_old_connections()
            try:
                actor=User.objects.get(pk=user.pk)
                data={'draft':{'mode':'text','text':'Закупка '+str(index)}}
                try:
                    return idempotent(actor,'query','quota-key-'+str(index),data,lambda:manual_query(actor,data))[1]
                except ApiProblem as exc:return exc.status
            finally:close_old_connections()
        with patch('api.services.MAX_QUERIES',1), ThreadPoolExecutor(max_workers=2) as pool:
            codes=list(pool.map(run,range(2)))
        self.assertEqual(sorted(codes),[201,413]);self.assertEqual(Query.objects.count(),1)

    def test_concurrent_throttle_cannot_lose_increment(self):
        from .views import throttle
        request=RequestFactory().post('/',REMOTE_ADDR='127.0.0.9')
        for _ in range(9):throttle(request,'parallel-throttle')
        def run(_):
            close_old_connections()
            try:
                try:throttle(request,'parallel-throttle');return 200
                except ApiProblem as exc:return exc.status
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(run,range(2)))
        self.assertEqual(sorted(codes),[200,429]);self.assertEqual(sorted(AuthAttempt.objects.values_list('count',flat=True)),[10,10])

    def test_concurrent_same_key_creates_only_one_query_and_retry_recovers(self):
        user=User.objects.create_user('parallel@example.test',PASSWORD,name='Параллель')
        payload={'draft':{'mode':'text','text':'Поставка бумаги'}}
        def run():
            close_old_connections()
            from django.db import OperationalError
            import time
            try:
                for attempt in range(5):
                    try:
                        actor=User.objects.get(pk=user.pk)
                        return idempotent(actor,'query','concurrent-key',payload,lambda:manual_query(actor,payload))[0]['id']
                    except OperationalError:
                        time.sleep(.05)
                raise AssertionError('Persistent database contention')
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(ids[0],ids[1]);self.assertEqual(Query.objects.count(),1);self.assertEqual(Mutation.objects.count(),1)
