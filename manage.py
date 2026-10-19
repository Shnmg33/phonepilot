"""Small launcher; .env accepts literal KEY=value lines without shell expansion."""
import argparse
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator:
                raise SystemExit('.env 每行必须为 KEY=value')
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PhonePilot 服务管理')
    parser.add_argument('command', choices=['init', 'run', 'doctor'])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.command == 'init':
        path = ROOT / '.env'
        with path.open('x') as f:
            os.chmod(path, 0o600)
            f.write(f'ADMIN_TOKEN={secrets.token_urlsafe(32)}\nBRIDGE_TOKEN={secrets.token_urlsafe(32)}\nDEEPSEEK_API_KEY=\nOPENAI_API_KEY=\nAUTO_ACTIVATE_SKILLS=false\n')
        print('已创建 .env 并生成两个独立令牌。请填入模型密钥；ADMIN_TOKEN 用于网页，BRIDGE_TOKEN 用于本地桥接。')
    else:
        load_env()
        if args.command == 'doctor':
            for name in ('ADMIN_TOKEN', 'BRIDGE_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
                print(f'{name}: ' + ('已配置' if os.getenv(name) else '未配置'))
            print('数据库: ' + os.getenv('DATABASE_PATH', str(ROOT / 'data/phonepilot.db')))
        else:
            import uvicorn
            uvicorn.run('server.app:app', host=args.host, port=args.port, workers=1)
