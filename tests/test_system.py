import asyncio
import base64
import json
import os
import shlex
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError

from bridge.agent import ADB
from server.app import create_app
from server.models import Action, ProviderInput, ScheduleInput
from server.runtime import Hub, Runtime, next_run
from server.store import Store

ADMIN = 'test-admin-' + 'a' * 32
BRIDGE = 'test-bridge-' + 'b' * 32
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jS1sAAAAASUVORK5CYII='


class FakeModel:
    def __init__(self):
        self.messages = []
        self.actions = 0

    async def complete(self, provider, messages):
        self.messages.append(messages)
        if '实际执行轨迹' in messages[0]['content']:
            return {'task_review':'进入关于手机并读取系统版本，已确认版本为 15。', 'title':'设置中查看版本', 'app':'com.android.settings', 'trigger':'查看 Android 版本',
                    'steps':['点击“关于手机”','读取 Android 版本并验证'], 'cautions':'界面随系统版本变化', 'evidence_steps':[1]}
        self.actions += 1
        if self.actions % 2:
            return {'type':'tap','node_id':0,'reason':'进入关于手机'}
        return {'type':'done','reason':'最新界面显示 Android 版本 15，目标已完成'}


class SystemTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ADMIN_TOKEN':ADMIN,'BRIDGE_TOKEN':BRIDGE,'AUTO_ACTIVATE_SKILLS':'false'})
        self.env.start()
        self.model = FakeModel()
        self.app = create_app(str(Path(self.temp.name)/'test.db'), self.model)
        self.life = self.app.router.lifespan_context(self.app)
        await self.life.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test', headers={'Authorization':'Bearer '+ADMIN})
        self.bridge_headers = {'Authorization':'Bearer '+BRIDGE}
        self.device = {'serial':'USB123','name':'Test Android','state':'device','transport':'USB'}
        await self.poll()

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.life.__aexit__(None,None,None)
        self.env.stop()
        self.temp.cleanup()

    async def poll(self):
        return await self.client.post('/api/bridge/poll', json={'bridge_id':'home','devices':[self.device]}, headers=self.bridge_headers)

    async def simulate(self, task_id):
        performed = []
        deadline = time.time()+8
        while time.time()<deadline:
            response = await self.poll()
            cmd = response.json()['command']
            if cmd:
                if cmd['operation']=='observe':
                    result = {'width':1080,'height':1920,'package':'com.android.settings','screenshot':PNG,
                              'nodes':[{'id':0,'text':'关于手机' if not performed else 'Android 版本 15','bounds':[0,100,400,200],'enabled':True}]}
                else:
                    performed.append(cmd['payload'])
                    result = {'ok':True}
                reply = await self.client.post('/api/bridge/result', headers=self.bridge_headers,
                    json={'bridge_id':'home','command_id':cmd['id'],'result':result})
                self.assertTrue(reply.json()['accepted'])
            state = (await self.client.get('/api/state')).json()
            task = next(t for t in state['tasks'] if t['id']==task_id)
            if task['status'] not in ('queued','running') and self.app.state.runtime.active_id != task_id:
                return state, performed
            await asyncio.sleep(.02)
        self.fail('模拟任务超时')

    async def test_full_execution_learning_review_and_reuse(self):
        response = await self.client.post('/api/tasks',json={'goal':'查看 Android 版本','device':'home:USB123'})
        self.assertEqual(response.status_code,200)
        task_id=response.json()['id']
        state, performed=await self.simulate(task_id)
        self.assertEqual(performed[0]['x'],200)
        self.assertEqual(performed[0]['y'],150)
        self.assertEqual(state['tasks'][0]['status'],'succeeded')
        self.assertIn('确认版本',state['tasks'][0]['review'])
        skill=state['skills'][0]
        self.assertEqual(skill['status'],'draft')
        self.assertEqual(json.loads(skill['evidence']),[1])
        self.assertEqual(skill['source_task'],task_id)
        self.assertEqual((await self.client.get('/api/tasks/'+task_id)).json()['id'],task_id)
        self.assertNotIn('screenshot', json.loads(self.model.messages[0][1]['content'])['screen'])
        payload={k:skill[k] for k in ('title','app','trigger','cautions')}
        payload.update(steps=json.loads(skill['steps']),status='active')
        self.assertEqual((await self.client.put('/api/skills/'+skill['id'],json=payload)).status_code,200)
        versions=(await self.client.get('/api/skills/'+skill['id']+'/versions')).json()
        self.assertEqual([v['version'] for v in versions],[2,1])
        new=(await self.client.post('/api/tasks',json={'goal':'再次查看 Android 版本','device':'home:USB123'})).json()['id']
        state,_=await self.simulate(new)
        events=(await self.client.get('/api/tasks/'+new+'/events')).json()
        self.assertTrue(any(e['kind']=='memory' for e in events))
        original=next(s for s in state['skills'] if s['id']==skill['id'])
        self.assertEqual(original['uses'],1)
        self.assertEqual(original['successes'],1)

    async def test_auth_roles_validation_and_static_app(self):
        self.assertEqual((await self.client.get('/api/state',headers={'Authorization':'Bearer '+BRIDGE})).status_code,401)
        self.assertEqual((await self.client.get('/api/state',headers={'Authorization':''})).status_code,401)
        self.assertEqual((await self.client.post('/api/bridge/poll',json={'bridge_id':'home','devices':[]})).status_code,401)
        html=await self.client.get('/')
        self.assertIn('PhonePilot',html.text)
        self.assertIn("script-src 'self'",html.headers['content-security-policy'])
        self.assertEqual((await self.client.get('/static/app.js')).status_code,200)
        self.assertEqual((await self.client.post('/api/devices/home:USB123/action',json={'type':'shell','reason':'x'})).status_code,422)
        self.assertEqual((await self.client.post('/api/tasks',json={'goal':'测试','device':'missing'})).status_code,400)
        self.assertEqual((await self.client.post('/api/tasks',json={'goal':'测试','device':'home:USB123','max_steps':1000})).status_code,422)

    async def test_schedules_persist_and_do_not_overlap(self):
        spec={'goal':'查看版本','name':'每小时检查','device':'home:USB123','kind':'interval','interval_seconds':3600}
        response=await self.client.post('/api/schedules',json=spec)
        self.assertEqual(response.status_code,200)
        sid=response.json()['id']
        # Pause task worker, leaving scheduler active; queued occurrence must deduplicate.
        self.app.state.runtime.background[0].cancel()
        await asyncio.gather(self.app.state.runtime.background[0],return_exceptions=True)
        self.app.state.store.execute('UPDATE schedules SET next_run=? WHERE id=?',(time.time()-10,sid))
        await asyncio.sleep(1.1)
        queued=self.app.state.store.all('SELECT * FROM tasks WHERE schedule_id=?',(sid,))
        self.assertEqual(len(queued),1)
        self.app.state.store.execute('UPDATE schedules SET next_run=? WHERE id=?',(time.time()-10,sid))
        await asyncio.sleep(1.1)
        self.assertEqual(len(self.app.state.store.all('SELECT * FROM tasks WHERE schedule_id=?',(sid,))),1)
        row=self.app.state.store.one('SELECT * FROM schedules WHERE id=?',(sid,))
        self.assertGreater(row['next_run'],time.time())
        await self.client.post('/api/schedules/'+sid+'/toggle')
        self.assertEqual(self.app.state.store.one('SELECT * FROM schedules WHERE id=?',(sid,))['enabled'],0)

    async def test_offline_device_waits_in_queue_until_reconnected(self):
        self.app.state.hub.devices['home:USB123']['connected']=False
        task=(await self.client.post('/api/tasks',json={'goal':'查看 Android 版本','device':'home:USB123'})).json()['id']
        await asyncio.sleep(1.1)
        self.assertEqual(self.app.state.store.one('SELECT status FROM tasks WHERE id=?',(task,))['status'],'queued')
        state,_=await self.simulate(task)
        self.assertEqual(next(t for t in state['tasks'] if t['id']==task)['status'],'succeeded')

    async def test_android_locked_phone_waits_then_uses_text_only_observation(self):
        self.device.update(locked=True, interactive=False, transport='手机原生 · HTTPS',
                           capabilities={'adapter':'android-accessibility','text_semantics':'replace focused field'})
        await self.poll()
        task=(await self.client.post('/api/tasks',json={'goal':'查看 Android 版本','device':'home:USB123'})).json()['id']
        await asyncio.sleep(1.1)
        current=(await self.client.get('/api/state')).json()
        self.assertTrue(current['devices'][0]['online'])
        self.assertFalse(current['devices'][0]['ready'])
        self.assertEqual(current['tasks'][0]['status'],'queued')
        self.device.update(locked=False,interactive=True)
        state,_=await self.simulate(task)
        self.assertEqual(state['tasks'][0]['status'],'succeeded')
        context=json.loads(self.model.messages[0][1]['content'])
        self.assertEqual(context['device_capabilities']['adapter'],'android-accessibility')

    async def test_long_poll_wakes_for_command_and_validates_wait(self):
        poll=asyncio.create_task(self.client.post('/api/bridge/poll',headers=self.bridge_headers,
            json={'bridge_id':'home','devices':[self.device],'wait_seconds':2}))
        await asyncio.sleep(.05)
        self.assertFalse(poll.done())
        rpc=asyncio.create_task(self.app.state.hub.rpc('home:USB123','observe',{'include_screenshot':False}))
        response=await asyncio.wait_for(poll,1)
        command=response.json()['command']
        self.assertFalse(command['payload']['include_screenshot'])
        await self.client.post('/api/bridge/result',headers=self.bridge_headers,
            json={'bridge_id':'home','command_id':command['id'],'result':{'nodes':[]}})
        self.assertEqual(await rpc,{'nodes':[]})
        invalid=await self.client.post('/api/bridge/poll',headers=self.bridge_headers,
            json={'bridge_id':'home','devices':[self.device],'wait_seconds':300})
        self.assertEqual(invalid.status_code,422)

    async def test_failure_and_stop_preserve_truthful_status(self):
        self.model.complete=AsyncMock(return_value={'type':'tap','node_id':999,'reason':'错误节点'})
        task=(await self.client.post('/api/tasks',json={'goal':'错误动作测试','device':'home:USB123'})).json()['id']
        state,actions=await self.simulate(task)
        self.assertEqual(actions,[])
        self.assertEqual(state['tasks'][0]['status'],'failed')
        self.assertEqual(state['skills'],[])
        task=(await self.client.post('/api/tasks',json={'goal':'停止测试','device':'home:USB123'})).json()['id']
        command=None
        for _ in range(100):
            command=(await self.poll()).json()['command']
            if command:break
            await asyncio.sleep(.02)
        self.assertIsNotNone(command)
        await self.client.post('/api/tasks/'+task+'/stop')
        await asyncio.sleep(.05)
        self.assertEqual(self.app.state.store.one('SELECT status FROM tasks WHERE id=?',(task,))['status'],'cancelled')
        self.assertIn('home:USB123',self.app.state.hub.inflight)
        await self.client.post('/api/bridge/result',headers=self.bridge_headers,json={'bridge_id':'home','command_id':command['id'],'result':{}})
        self.assertNotIn('home:USB123',self.app.state.hub.inflight)

    async def test_bridge_cannot_ack_another_bridge_command(self):
        future=asyncio.create_task(self.app.state.hub.rpc('home:USB123','observe'))
        await asyncio.sleep(0)
        cmd=(await self.poll()).json()['command']
        response=await self.client.post('/api/bridge/result',headers=self.bridge_headers,
            json={'bridge_id':'other','command_id':cmd['id'],'result':{}})
        self.assertFalse(response.json()['accepted'])
        self.assertFalse(future.done())
        await self.client.post('/api/bridge/result',headers=self.bridge_headers,
            json={'bridge_id':'home','command_id':cmd['id'],'result':{'ok':True}})
        self.assertEqual(await future,{'ok':True})


class UnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_learning_requires_real_evidence_and_failed_runs_stay_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(str(Path(tmp)/'test.db'))
            task_id=store.task('查看系统版本','device','deepseek')
            task=store.one('SELECT * FROM tasks WHERE id=?',(task_id,))
            model=FakeModel()
            runtime=Runtime(store,Hub(),model)
            payload={'title':'版本查询经验','trigger':'查询系统版本','steps':['查看关于手机'], 'evidence_steps':[999]}
            model.complete=AsyncMock(return_value=payload)
            with self.assertRaisesRegex(ValueError,'执行证据'):
                await runtime.learn(task,{},[{'step':1}], 'succeeded','done',{})
            self.assertEqual(store.all('SELECT * FROM skills'),[])
            payload['evidence_steps']=[1]
            with patch.dict(os.environ,{'AUTO_ACTIVATE_SKILLS':'true'}):
                await runtime.learn(task,{},[{'step':1}], 'failed','未完成',{})
                self.assertEqual(store.all('SELECT * FROM skills')[0]['status'],'draft')
                await runtime.learn(task,{},[{'step':1}], 'succeeded','已完成',{})
                self.assertEqual(len(store.all("SELECT * FROM skills WHERE status='active'")),1)
            store.db.close()

    async def test_model_uses_configured_endpoint_and_json_protocol(self):
        from server.runtime import ModelClient
        request_args={}
        class Client:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def post(self,url,**kwargs):
                request_args.update(url=url,**kwargs)
                return httpx.Response(200,json={'choices':[{'message':{'content':'{"type":"done","reason":"observed"}'}}]})
        with patch.dict(os.environ,{'TEST_API_KEY':'not-a-real-key'}), patch('server.runtime.httpx.AsyncClient',return_value=Client()):
            result=await ModelClient().complete({'base_url':'https://api.deepseek.com','key_env':'TEST_API_KEY','model':'deepseek-chat'},[{'role':'user','content':'test'}])
        self.assertEqual(result['type'],'done')
        self.assertEqual(request_args['url'],'https://api.deepseek.com/chat/completions')
        self.assertEqual(request_args['headers']['Authorization'],'Bearer not-a-real-key')
        self.assertEqual(request_args['json']['response_format'],{'type':'json_object'})

    async def test_hub_timeout_is_not_replayed_and_late_result_recovers(self):
        hub=Hub();hub.heartbeat('home',[{'serial':'one','state':'device'}])
        pending=asyncio.create_task(hub.rpc('home:one','action',{'type':'key'},timeout=.05))
        await asyncio.sleep(0)
        command=hub.claim('home')
        self.assertIsNone(hub.claim('home'))
        with self.assertRaisesRegex(RuntimeError,'超时'):
            await pending
        with self.assertRaisesRegex(RuntimeError,'未确认'):
            await hub.rpc('home:one','observe')
        self.assertFalse(hub.result('home',command['id'],{'ok':True},None))
        self.assertNotIn('home:one',hub.inflight)

    async def test_unconfirmed_command_blocks_new_tasks_until_result(self):
        hub=Hub(); hub.heartbeat('phone',[{'serial':'one','state':'device','locked':False,'interactive':True}])
        self.assertTrue(hub.can_run('phone:one'))
        rpc=asyncio.create_task(hub.rpc('phone:one','action',{'type':'key'}))
        await asyncio.sleep(0)
        command=hub.claim('phone')
        self.assertFalse(hub.can_run('phone:one'))
        hub.result('phone',command['id'],{'ok':True},None)
        await rpc
        self.assertTrue(hub.can_run('phone:one'))

    async def test_adb_remote_shell_quotes_input_and_unicode_requirements(self):
        adb=ADB();adb.run=AsyncMock(return_value=b'')
        text="hello; $(id) `whoami` 'quotes' & \"double\""
        await adb.action('SERIAL',{'type':'text','text':text,'reason':'test'})
        call=adb.run.call_args.args
        self.assertEqual(call[:3],('-s','SERIAL','shell'))
        self.assertEqual(shlex.split(call[3]),['input','text',text.replace(' ','%s')])
        adb.run=AsyncMock(return_value=b'other/.IME')
        with self.assertRaisesRegex(RuntimeError,'ADBKeyboard'):
            await adb.action('SERIAL',{'type':'text','text':'中文','reason':'test'})
        with self.assertRaises(ValidationError):
            Action(type='launch',package='com.good;reboot',reason='test')

    async def test_observation_redacts_password_and_extracts_nodes(self):
        adb=ADB();adb.screenshot=AsyncMock(return_value={'screenshot':PNG,'width':1080,'height':1920})
        xml=b'<hierarchy><node bounds="[0,0][100,100]" text="secret" password="true" enabled="true" package="com.example.app"/><node bounds="[0,100][100,200]" text="About" enabled="true" package="com.example.app"/></hierarchy>'
        adb.shell=AsyncMock(side_effect=[b'UI hierarchy dumped',xml])
        obs=await adb.observe('serial')
        self.assertEqual(obs['nodes'][0]['text'],'[password]')
        self.assertEqual(obs['package'],'com.example.app')
        self.assertEqual(obs['nodes'][1]['id'],1)

    async def test_schedule_timezone_and_input_validation(self):
        now=datetime(2026,10,19,0,0,tzinfo=timezone.utc).timestamp()
        result=next_run({'kind':'daily','daily_time':'09:00','timezone':'Asia/Shanghai'},now)
        self.assertEqual(datetime.fromtimestamp(result,timezone.utc).hour,1)
        # Spring-forward missing 02:30 skips to the next valid day.
        dst=datetime(2026,3,8,6,59,tzinfo=timezone.utc).timestamp()
        result=next_run({'kind':'daily','daily_time':'02:30','timezone':'America/New_York'},dst)
        self.assertEqual(datetime.fromtimestamp(result,timezone.utc).day,9)
        with self.assertRaises(ValidationError):
            ScheduleInput(goal='test',device='a',name='x',daily_time='99:00')
        with self.assertRaises(ValidationError):
            ProviderInput(id='x',name='x',base_url='https://secret@example.com',model='m',key_env='CUSTOM_API_KEY')

    async def test_restart_marks_running_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'db.sqlite')
            s=Store(path);task=s.task('test','device','deepseek')
            s.execute("UPDATE tasks SET status='running' WHERE id=?",(task,));s.db.close()
            s=Store(path)
            self.assertEqual(s.one('SELECT status FROM tasks WHERE id=?',(task,))['status'],'interrupted')
            s.db.close()


if __name__=='__main__':
    unittest.main()
