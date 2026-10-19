import asyncio
import base64
import hmac
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .models import Action, ProviderInput, ScheduleInput, SkillInput, TaskInput
from .runtime import Hub, ModelClient, Runtime, next_run
from .store import Store, uid

ROOT = Path(__file__).resolve().parent.parent


def create_app(db_path=None, model=None):
    @asynccontextmanager
    async def lifespan(app):
        for name in ('ADMIN_TOKEN', 'BRIDGE_TOKEN'):
            if len(os.getenv(name, '')) < 24:
                raise RuntimeError(f'{name} 必须配置为至少 24 字符的随机令牌。参见 README。')
        if os.getenv('ADMIN_TOKEN') == os.getenv('BRIDGE_TOKEN'):
            raise RuntimeError('ADMIN_TOKEN 与 BRIDGE_TOKEN 必须不同')
        app.state.store = Store(db_path or os.getenv('DATABASE_PATH', str(ROOT / 'data/phonepilot.db')))
        app.state.hub = Hub()
        app.state.runtime = Runtime(app.state.store, app.state.hub, model)
        app.state.runtime.start()
        yield
        await app.state.runtime.close()
        app.state.store.db.close()

    app = FastAPI(title='PhonePilot', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def require(request: Request, env):
        expected = os.getenv(env, '')
        supplied = request.headers.get('authorization', '')
        if not expected or not hmac.compare_digest(supplied, 'Bearer ' + expected):
            raise HTTPException(401, '访问令牌无效')

    async def admin(request: Request):
        await require(request, 'ADMIN_TOKEN')

    async def bridge(request: Request):
        await require(request, 'BRIDGE_TOKEN')

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def store():
        return app.state.store

    def hub():
        return app.state.hub

    def validate_task(spec):
        if not store().one('SELECT id FROM providers WHERE id=?', (spec.provider,)):
            raise HTTPException(400, '模型配置不存在')
        if spec.device not in hub().devices:
            raise HTTPException(400, '请先连接并选择设备')

    @app.get('/api/health')
    async def health():
        return {'status': 'ok'}

    @app.get('/api/state', dependencies=[Depends(admin)])
    async def state():
        providers = store().all('SELECT * FROM providers')
        for p in providers:
            p['configured'] = bool(os.getenv(p['key_env']))
        return {'devices': [{**d, 'online': hub().online(d['id']), 'ready': hub().can_run(d['id']), 'busy': hub().lock(d['id']).locked(), 'unsettled': d['id'] in hub().inflight} for d in hub().devices.values()],
                'tasks': store().all('SELECT * FROM tasks ORDER BY created DESC LIMIT 150'),
                'schedules': store().all('SELECT * FROM schedules ORDER BY name'),
                'skills': store().all('SELECT * FROM skills ORDER BY updated DESC'),
                'providers': providers, 'auto_activate': os.getenv('AUTO_ACTIVATE_SKILLS', 'false').lower() == 'true'}

    @app.post('/api/tasks', dependencies=[Depends(admin)])
    async def create_task(body: TaskInput):
        validate_task(body)
        return {'id': store().task(**body.model_dump())}

    @app.get('/api/tasks/{task_id}/events', dependencies=[Depends(admin)])
    async def events(task_id: str):
        return store().all('SELECT * FROM events WHERE task_id=? ORDER BY id', (task_id,))

    @app.get('/api/tasks/{task_id}', dependencies=[Depends(admin)])
    async def get_task(task_id: str):
        task = store().one('SELECT * FROM tasks WHERE id=?', (task_id,))
        if not task:
            raise HTTPException(404, '任务不存在')
        return task

    @app.post('/api/tasks/{task_id}/stop', dependencies=[Depends(admin)])
    async def stop(task_id: str):
        task = store().one('SELECT * FROM tasks WHERE id=?', (task_id,))
        if not task:
            raise HTTPException(404, '任务不存在')
        runtime = app.state.runtime
        if task['status'] == 'queued':
            store().execute("UPDATE tasks SET status='cancelled',finished=?,summary='用户取消排队任务' WHERE id=?", (time.time(), task_id))
        elif task['status'] == 'running' and runtime.active_id == task_id and runtime.active_job:
            runtime.active_job.cancel()
        return {'ok': True}

    @app.post('/api/schedules', dependencies=[Depends(admin)])
    async def create_schedule(body: ScheduleInput):
        validate_task(body)
        spec = body.model_dump()
        schedule_id = uid()
        store().execute('''INSERT INTO schedules(id,name,goal,device,provider,kind,interval_seconds,daily_time,timezone,next_run,max_steps)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (schedule_id, body.name, body.goal, body.device, body.provider,
                            body.kind, body.interval_seconds, body.daily_time, body.timezone, next_run(spec), body.max_steps))
        return {'id': schedule_id}

    @app.post('/api/schedules/{schedule_id}/toggle', dependencies=[Depends(admin)])
    async def toggle_schedule(schedule_id: str):
        spec = store().one('SELECT * FROM schedules WHERE id=?', (schedule_id,))
        if not spec:
            raise HTTPException(404, '计划不存在')
        store().execute('UPDATE schedules SET enabled=?,next_run=? WHERE id=?', (1-int(spec['enabled']), next_run(spec), schedule_id))
        return {'ok': True}

    @app.delete('/api/schedules/{schedule_id}', dependencies=[Depends(admin)])
    async def delete_schedule(schedule_id: str):
        store().execute('DELETE FROM schedules WHERE id=?', (schedule_id,))
        return {'ok': True}

    @app.post('/api/skills', dependencies=[Depends(admin)])
    async def create_skill(body: SkillInput):
        return {'id': store().add_skill(body.model_dump(), status=body.status)}

    @app.put('/api/skills/{skill_id}', dependencies=[Depends(admin)])
    async def edit_skill(skill_id: str, body: SkillInput):
        if not store().one('SELECT id FROM skills WHERE id=?', (skill_id,)):
            raise HTTPException(404, '技能不存在')
        store().execute('UPDATE skills SET title=?,app=?,trigger=?,steps=?,cautions=?,status=?,version=version+1,updated=? WHERE id=?',
                        (body.title, body.app, body.trigger, json.dumps(body.steps, ensure_ascii=False), body.cautions, body.status, time.time(), skill_id))
        store().snapshot_skill(skill_id)
        return {'ok': True}

    @app.get('/api/skills/{skill_id}/versions', dependencies=[Depends(admin)])
    async def versions(skill_id: str):
        return store().all('SELECT * FROM skill_versions WHERE skill_id=? ORDER BY version DESC', (skill_id,))

    @app.put('/api/providers', dependencies=[Depends(admin)])
    async def provider(body: ProviderInput):
        store().execute('INSERT INTO providers VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,base_url=excluded.base_url,model=excluded.model,key_env=excluded.key_env,vision=excluded.vision',
                        (body.id, body.name, body.base_url, body.model, body.key_env, int(body.vision)))
        return {'ok': True}

    @app.post('/api/providers/{provider_id}/test', dependencies=[Depends(admin)])
    async def test_provider(provider_id: str):
        p = store().one('SELECT * FROM providers WHERE id=?', (provider_id,))
        if not p:
            raise HTTPException(404, '配置不存在')
        try:
            await app.state.runtime.model.complete(p, [{'role': 'user', 'content': 'Return a JSON object: {"ok":true}'}])
            return {'ok': True}
        except Exception as exc:
            raise HTTPException(400, str(exc)[:500])

    @app.get('/api/devices/{device:path}/screen', dependencies=[Depends(admin)])
    async def screen(device: str):
        if hub().lock(device).locked():
            cached = hub().screens.get(device)
            if cached:
                return Response(base64.b64decode(cached, validate=True), media_type='image/png', headers={'X-Screen-Source': 'last-observation'})
            raise HTTPException(409, 'AI 正在操作设备，请任务结束后刷新预览')
        async with hub().lock(device):
            try:
                result = await hub().rpc(device, 'screenshot')
                return Response(base64.b64decode(result['screenshot'], validate=True), media_type='image/png')
            except Exception as exc:
                raise HTTPException(400, str(exc)[:500])

    @app.post('/api/devices/{device:path}/action', dependencies=[Depends(admin)])
    async def manual_action(device: str, body: Action):
        if body.type in ('done', 'blocked') or (body.type == 'tap' and (body.x is None or body.y is None)):
            raise HTTPException(400, '手动操作需要可执行动作和完整坐标')
        if hub().lock(device).locked():
            raise HTTPException(409, '设备正在执行任务，请先停止任务')
        async with hub().lock(device):
            try:
                return await hub().rpc(device, 'action', body.model_dump(exclude_none=True))
            except Exception as exc:
                raise HTTPException(400, str(exc)[:500])

    @app.post('/api/devices/{device:path}/recover', dependencies=[Depends(admin)])
    async def recover_device(device: str):
        if hub().lock(device).locked():
            raise HTTPException(409, '请先停止正在运行的任务')
        hub().inflight.pop(device, None)
        return {'ok': True}

    class BridgePoll(BaseModel):
        bridge_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
        devices: list[dict] = Field(default_factory=list, max_length=30)
        wait_seconds: int = Field(default=0, ge=0, le=20)

    @app.post('/api/bridge/poll', dependencies=[Depends(bridge)])
    async def poll(body: BridgePoll):
        for d in body.devices:
            if not isinstance(d.get('serial'), str) or len(d['serial']) > 150 or d.get('state') not in ('device', 'offline', 'unauthorized'):
                raise HTTPException(400, '设备信息格式错误')
        hub().heartbeat(body.bridge_id, body.devices)
        return {'command': await hub().claim_wait(body.bridge_id, body.wait_seconds)}

    class BridgeResult(BaseModel):
        bridge_id: str
        command_id: str
        result: dict = Field(default_factory=dict)
        error: str | None = Field(default=None, max_length=2000)

    @app.post('/api/bridge/result', dependencies=[Depends(bridge)])
    async def result(body: BridgeResult):
        return {'accepted': hub().result(body.bridge_id, body.command_id, body.result, body.error)}

    @app.get('/')
    async def index():
        return FileResponse(ROOT / 'web/index.html')

    app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
    return app


app = create_app()
