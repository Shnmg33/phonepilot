"""Outbound-only ADB bridge. Run on the computer physically near your Android phone."""
import argparse
import asyncio
import base64
import json
import os
import re
import shlex
import struct
import time
import xml.etree.ElementTree as ET

import httpx

from server.models import Action


class ADB:
    def __init__(self, executable='adb'):
        self.executable = executable

    async def run(self, *args, timeout=25):
        proc = await asyncio.create_subprocess_exec(self.executable, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            proc.kill()
            await proc.communicate()
            raise
        if proc.returncode:
            raise RuntimeError('ADB: ' + err.decode(errors='replace')[:500])
        return out

    async def shell(self, serial, *args, timeout=25):
        # adb invokes a remote shell even when the host uses argv; quote every remote argument.
        return await self.run('-s', serial, 'shell', ' '.join(shlex.quote(str(a)) for a in args), timeout=timeout)

    async def devices(self):
        output = (await self.run('devices', '-l')).decode(errors='replace')
        result = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ('device', 'offline', 'unauthorized'):
                model = next((s.split(':', 1)[1].replace('_', ' ') for s in parts[2:] if s.startswith('model:')), parts[0])
                result.append({'serial': parts[0], 'state': parts[1], 'name': model, 'transport': '无线 ADB' if ':' in parts[0] else 'USB'})
        return result

    async def screenshot(self, serial):
        data = await self.run('-s', serial, 'exec-out', 'screencap', '-p')
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) < 24:
            raise RuntimeError('无法读取截图；请解锁手机，部分安全界面禁止截屏')
        width, height = struct.unpack('>II', data[16:24])
        return {'screenshot': base64.b64encode(data).decode(), 'width': width, 'height': height}

    async def observe(self, serial):
        screen = await self.screenshot(serial)
        nodes, warning = [], ''
        try:
            await self.shell(serial, 'uiautomator', 'dump', '/sdcard/phonepilot-window.xml', timeout=30)
            xml = await self.shell(serial, 'cat', '/sdcard/phonepilot-window.xml')
            root = ET.fromstring(xml)
            for el in root.iter('node'):
                b = [int(x) for x in re.findall(r'-?\d+', el.get('bounds', ''))]
                if len(b) != 4 or b[2] <= b[0] or b[3] <= b[1]:
                    continue
                if not any(el.get(k) not in (None, '', 'false') for k in ('text', 'content-desc', 'clickable', 'scrollable', 'focusable')):
                    continue
                password = el.get('password') == 'true'
                nodes.append({'id': len(nodes), 'text': '[password]' if password else el.get('text', '')[:400],
                              'description': '' if password else el.get('content-desc', '')[:400], 'resource_id': el.get('resource-id', ''),
                              'class': el.get('class', ''), 'package': el.get('package', ''), 'bounds': b,
                              'clickable': el.get('clickable') == 'true', 'scrollable': el.get('scrollable') == 'true',
                              'enabled': el.get('enabled') == 'true'})
                if len(nodes) >= 250:
                    warning = '界面节点较多，已截取前 250 个'
                    break
        except (ET.ParseError, RuntimeError, asyncio.TimeoutError):
            warning = '无法获取可访问性节点；文本模型应停止，或切换视觉模型'
        package = next((n['package'] for n in nodes if n['package'] not in ('com.android.systemui', '')), '')
        return {**screen, 'nodes': nodes, 'package': package, 'warning': warning}

    async def action(self, serial, payload):
        a = Action.model_validate(payload)
        if a.type in ('done', 'blocked'):
            raise ValueError('此动作不能发送至 ADB')
        if a.type in ('tap', 'swipe'):
            # Validate again at the local trust boundary, including current orientation.
            screen = await self.screenshot(serial)
            points = [(a.x, a.y)] + ([(a.x2, a.y2)] if a.type == 'swipe' else [])
            if any(x is None or y is None or not (0 <= x < screen['width'] and 0 <= y < screen['height']) for x,y in points):
                raise ValueError('操作坐标超出当前屏幕')
        if a.type == 'tap':
            await self.shell(serial, 'input', 'tap', a.x, a.y)
        elif a.type == 'swipe':
            await self.shell(serial, 'input', 'swipe', a.x, a.y, a.x2, a.y2, a.duration)
        elif a.type == 'key':
            await self.shell(serial, 'input', 'keyevent', 'KEYCODE_' + a.key)
        elif a.type == 'text':
            if a.text.isascii() and '\n' not in a.text and '\t' not in a.text and '%s' not in a.text:
                await self.shell(serial, 'input', 'text', a.text.replace(' ', '%s'))
            else:
                current = (await self.shell(serial, 'settings', 'get', 'secure', 'default_input_method')).decode().strip()
                if current != 'com.android.adbkeyboard/.AdbIME':
                    raise RuntimeError('中文/特殊文本输入需要在手机安装并启用 ADBKeyboard（见 README）；当前输入法不支持')
                encoded = base64.b64encode(a.text.encode()).decode()
                await self.shell(serial, 'am', 'broadcast', '-a', 'ADB_INPUT_B64', '-p', 'com.android.adbkeyboard', '--es', 'msg', encoded)
        elif a.type == 'launch':
            result = await self.shell(serial, 'monkey', '-p', a.package, '-c', 'android.intent.category.LAUNCHER', '1')
            if b'No activities found' in result or b'monkey aborted' in result.lower():
                raise RuntimeError('应用包不存在或没有可启动界面')
        elif a.type == 'wait':
            await asyncio.sleep(a.seconds)
        return {'ok': True}


async def serve(args):
    token = os.getenv('BRIDGE_TOKEN', '')
    if len(token) < 24:
        raise SystemExit('请设置 BRIDGE_TOKEN，必须与云端一致且至少 24 字符')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', args.id):
        raise SystemExit('bridge id 仅允许字母、数字、下划线、连字符')
    if not args.server.startswith('https://') and not (args.allow_http and args.server.startswith('http://')):
        raise SystemExit('云端地址必须使用 HTTPS；本地开发可显式指定 --allow-http')
    adb = ADB(args.adb)
    await adb.run('version')
    print(f'PhonePilot bridge {args.id} 已启动；只使用出站连接。', flush=True)
    async with httpx.AsyncClient(base_url=args.server.rstrip('/'), headers={'Authorization': 'Bearer ' + token}, timeout=15) as client:
        active = None
        async def execute(command):
            output = {'bridge_id': args.id, 'command_id': command['id'], 'result': {}}
            try:
                if time.time() > command['expires']:
                    raise RuntimeError('命令已过期，未执行')
                serial, op = command['serial'], command['operation']
                if op == 'observe':
                    result = await adb.observe(serial)
                elif op == 'screenshot':
                    result = await adb.screenshot(serial)
                elif op == 'action':
                    result = await adb.action(serial, command['payload'])
                else:
                    raise ValueError('未知桥接操作')
                output['result'] = result
            except Exception as exc:
                output['error'] = str(exc)[:1000]
            # Result delivery can be retried, but the phone operation is never replayed.
            for attempt in range(3):
                try:
                    response = await client.post('/api/bridge/result', json=output)
                    response.raise_for_status()
                    return
                except httpx.HTTPError:
                    await asyncio.sleep(1 + attempt)
            print('结果回传失败；未重复手机操作。请检查云端任务状态。', flush=True)

        try:
            while True:
                try:
                    devices = await adb.devices()
                    response = await client.post('/api/bridge/poll', json={'bridge_id': args.id, 'devices': devices})
                    response.raise_for_status()
                    command = response.json().get('command')
                    if command:
                        if active and not active.done():
                            await client.post('/api/bridge/result', json={'bridge_id': args.id, 'command_id': command['id'], 'error': '桥接端忙碌，请稍后重试'})
                        else:
                            active = asyncio.create_task(execute(command))
                except (httpx.HTTPError, RuntimeError, OSError):
                    print('连接失败，5 秒后重试；检查网络、令牌和 ADB。', flush=True)
                    await asyncio.sleep(4)
                await asyncio.sleep(1)
        finally:
            if active:
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, help='https://phone.example.com')
    parser.add_argument('--id', default='home', help='稳定且唯一的桥接标识')
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--allow-http', action='store_true', help='仅用于本机开发或可信 VPN 网络')
    asyncio.run(serve(parser.parse_args()))
