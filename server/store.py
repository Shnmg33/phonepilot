import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


def uid():
    return uuid.uuid4().hex[:16]


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, goal TEXT NOT NULL, device TEXT NOT NULL,
          provider TEXT NOT NULL, status TEXT NOT NULL, max_steps INTEGER,
          created REAL, started REAL, finished REAL, summary TEXT DEFAULT '',
          schedule_id TEXT, skill_ids TEXT DEFAULT '[]', review TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, at REAL,
          kind TEXT, message TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS skills (
          id TEXT PRIMARY KEY, title TEXT, app TEXT, trigger TEXT, steps TEXT,
          cautions TEXT, status TEXT, source_task TEXT, evidence TEXT,
          version INTEGER DEFAULT 1, uses INTEGER DEFAULT 0,
          successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0,
          created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS skill_versions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, skill_id TEXT, version INTEGER,
          at REAL, snapshot TEXT);
        CREATE TABLE IF NOT EXISTS providers (
          id TEXT PRIMARY KEY, name TEXT, base_url TEXT, model TEXT,
          key_env TEXT, vision INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS schedules (
          id TEXT PRIMARY KEY, name TEXT, goal TEXT, device TEXT, provider TEXT,
          kind TEXT, interval_seconds INTEGER, daily_time TEXT, timezone TEXT,
          next_run REAL, enabled INTEGER DEFAULT 1, max_steps INTEGER DEFAULT 25);
        CREATE INDEX IF NOT EXISTS events_task ON events(task_id,id);
        CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(status,created);
        CREATE INDEX IF NOT EXISTS schedules_due ON schedules(enabled,next_run);
        ''')
        if 'review' not in {r['name'] for r in self.db.execute('PRAGMA table_info(tasks)')}:
            self.db.execute("ALTER TABLE tasks ADD COLUMN review TEXT DEFAULT ''")
        self.db.executemany('INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?,?)', [
            ('deepseek', 'DeepSeek', 'https://api.deepseek.com', 'deepseek-chat', 'DEEPSEEK_API_KEY', 0),
            ('openai', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4.1-mini', 'OPENAI_API_KEY', 1),
        ])
        self.db.execute("UPDATE tasks SET status='interrupted',finished=?,summary='服务器重启，任务已中断；请检查手机状态后重新创建任务。' WHERE status='running'", (time.time(),))
        self.db.commit()

    def all(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None

    def execute(self, sql, args=()):
        cur = self.db.execute(sql, args)
        self.db.commit()
        return cur

    def event(self, task_id, kind, message, detail=None):
        self.execute('INSERT INTO events(task_id,at,kind,message,detail) VALUES(?,?,?,?,?)',
                     (task_id, time.time(), kind, message, json.dumps(detail, ensure_ascii=False) if detail is not None else None))

    def task(self, goal, device, provider, max_steps=25, schedule_id=None):
        task_id = uid()
        self.execute('INSERT INTO tasks(id,goal,device,provider,status,max_steps,created,schedule_id) VALUES(?,?,?,?,?,?,?,?)',
                     (task_id, goal, device, provider, 'queued', max_steps, time.time(), schedule_id))
        self.event(task_id, 'queued', '任务已进入队列')
        return task_id

    def snapshot_skill(self, skill_id):
        skill = self.one('SELECT * FROM skills WHERE id=?', (skill_id,))
        self.execute('INSERT INTO skill_versions(skill_id,version,at,snapshot) VALUES(?,?,?,?)',
                     (skill_id, skill['version'], time.time(), json.dumps(skill, ensure_ascii=False)))

    def add_skill(self, item, source_task=None, evidence=None, status='draft'):
        skill_id = uid()
        self.execute('''INSERT INTO skills(id,title,app,trigger,steps,cautions,status,source_task,evidence,created,updated)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                     (skill_id, item['title'], item.get('app', ''), item['trigger'],
                      json.dumps(item['steps'], ensure_ascii=False), item.get('cautions', ''), status,
                      source_task, json.dumps(evidence or []), time.time(), time.time()))
        self.snapshot_skill(skill_id)
        return skill_id
