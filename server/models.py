import re
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskInput(BaseModel):
    goal: str = Field(min_length=2, max_length=4000)
    device: str = Field(min_length=1, max_length=200)
    provider: str = 'deepseek'
    max_steps: int = Field(default=25, ge=1, le=100)


class ScheduleInput(TaskInput):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['interval', 'daily'] = 'daily'
    interval_seconds: int = Field(default=3600, ge=60, le=31536000)
    daily_time: str = '09:00'
    timezone: str = 'Asia/Shanghai'

    @field_validator('daily_time')
    @classmethod
    def valid_time(cls, value):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
            raise ValueError('时间格式必须为 HH:MM')
        return value

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError('未知时区')
        return value


class ProviderInput(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(max_length=500)
    model: str = Field(min_length=1, max_length=100)
    key_env: str = Field(pattern=r'^[A-Z][A-Z0-9_]{0,80}_API_KEY$')
    vision: bool = False

    @field_validator('base_url')
    @classmethod
    def valid_url(cls, value):
        u = urlparse(value)
        if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('请输入不含凭证的 HTTP(S) API 基础地址')
        return value.rstrip('/')


class SkillInput(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    app: str = Field(default='', max_length=200)
    trigger: str = Field(min_length=1, max_length=2000)
    steps: list[str] = Field(min_length=1, max_length=30)
    cautions: str = Field(default='', max_length=4000)
    status: Literal['draft', 'active', 'disabled'] = 'draft'

    @field_validator('steps')
    @classmethod
    def valid_steps(cls, steps):
        if any(not s.strip() or len(s) > 2000 for s in steps):
            raise ValueError('每个步骤必须为 1–2000 字符')
        return steps


class Action(BaseModel):
    type: Literal['tap', 'swipe', 'text', 'key', 'launch', 'wait', 'done', 'blocked']
    reason: str = Field(min_length=1, max_length=1500)
    node_id: int | None = Field(default=None, ge=0)
    x: int | None = Field(default=None, ge=0, le=20000)
    y: int | None = Field(default=None, ge=0, le=20000)
    x2: int | None = Field(default=None, ge=0, le=20000)
    y2: int | None = Field(default=None, ge=0, le=20000)
    duration: int = Field(default=400, ge=100, le=3000)
    text: str | None = Field(default=None, max_length=2000)
    key: Literal['HOME', 'BACK', 'ENTER', 'DEL', 'APP_SWITCH', 'TAB'] | None = None
    package: str | None = Field(default=None, pattern=r'^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$', max_length=200)
    seconds: float = Field(default=1, ge=0.2, le=5)

    @model_validator(mode='after')
    def valid_args(self):
        if self.type == 'tap' and self.node_id is None and (self.x is None or self.y is None):
            raise ValueError('tap 需要 node_id 或坐标')
        if self.type == 'swipe' and any(v is None for v in (self.x, self.y, self.x2, self.y2)):
            raise ValueError('swipe 需要起止坐标')
        if self.type == 'text' and self.text is None:
            raise ValueError('text 缺少文本')
        if self.type == 'key' and not self.key:
            raise ValueError('key 缺少按键')
        if self.type == 'launch' and not self.package:
            raise ValueError('launch 缺少应用包名')
        return self
