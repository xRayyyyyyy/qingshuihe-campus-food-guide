"""Expiring per-browser sessions; state is committed only after a successful turn."""
import asyncio
import copy
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from uuid import uuid4

from app.schemas.food import FoodFilters


class SessionError(Exception):
    def __init__(self, code, message, session=None):
        self.detail = {"code": code, "message": message}
        if session:
            self.detail.update(state_version=session.version,
                               constraints=session.filters.model_dump())
        super().__init__(message)


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid4()))
    version: int = 0
    filters: FoodFilters = field(default_factory=FoodFilters)
    candidates: dict = field(default_factory=dict)
    displayed_ids: list = field(default_factory=list)
    history: list = field(default_factory=list)
    pending_message: str = ""
    pending_changes: dict = field(default_factory=dict)
    result_meta: dict = field(default_factory=dict)
    touched_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    requests: OrderedDict = field(default_factory=OrderedDict)

    def remember_response(self, request_id, fingerprint, response):
        self.requests[request_id] = (fingerprint, copy.deepcopy(response))
        while len(self.requests) > 20:
            self.requests.popitem(last=False)


class SessionStore:
    def __init__(self, ttl=3600, max_sessions=500):
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.sessions = {}
        self.initial_requests = {}

    def get(self, session_id=None, request_id=None):
        now = time.monotonic()
        for key, session in list(self.sessions.items()):
            if now - session.touched_at > self.ttl and not session.lock.locked():
                self.sessions.pop(key, None)
        self.initial_requests = {key: value for key, value in self.initial_requests.items() if value in self.sessions}
        if not session_id and request_id in self.initial_requests:
            session_id = self.initial_requests[request_id]
        if session_id:
            session = self.sessions.get(str(session_id))
            if session is None:
                raise SessionError("session_expired", "会话已过期，请开始新对话。")
        else:
            if len(self.sessions) >= self.max_sessions:
                raise SessionError("session_capacity", "当前会话较多，请稍后重试。")
            session = Session()
            self.sessions[session.id] = session
            if request_id:
                self.initial_requests[request_id] = session.id
        session.touched_at = now
        return session
