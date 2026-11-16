"""Bidirectional Codex JSONL RPC. No user text is interpolated into a shell."""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from typing import Awaitable, Callable
from wsproto import WSConnection, ConnectionType
from wsproto.events import Request, AcceptConnection, TextMessage, Ping, CloseConnection


class RpcError(RuntimeError):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(payload.get("message", str(payload)))


class CompatibilityError(RuntimeError):
    pass


class RpcClient:
    def __init__(self, argv: list[str], *, websocket=False, on_event=None, on_request=None, on_disconnect=None):
        self.argv = argv
        self.on_event = on_event
        self.on_request = on_request
        self.on_disconnect = on_disconnect
        self.process = None
        self.pending = {}
        self.counter = 0
        self.tasks = set()
        self.stderr = deque(maxlen=10)
        self.closed = False
        self.reader = None
        self.stderr_reader = None
        self.ws = WSConnection(ConnectionType.CLIENT) if websocket else None
        self.handshake = None
        self.compatibility_error = None
        self.incompatible_threads = {}

    def spawn_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=32 * 1024 * 1024)
        self.reader = asyncio.create_task(self._read())
        self.stderr_reader = asyncio.create_task(self._read_stderr())
        try:
            if self.ws:
                self.handshake = asyncio.get_running_loop().create_future()
                self.process.stdin.write(self.ws.send(Request(host="localhost", target="/")))
                await self.process.stdin.drain()
                await asyncio.wait_for(self.handshake, 20)
            result = await self.request("initialize", {
                "clientInfo": {"name": "feishu_codex_workbench", "title": "飞书 Codex 工作台", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True}}, timeout=30)
            await self.write({"method": "initialized", "params": {}})
            return result
        except BaseException:
            await self.close()
            raise

    async def write(self, message):
        if self.closed or not self.process or self.process.returncode is not None:
            raise ConnectionError("Codex 连接已断开")
        data = json.dumps(message, ensure_ascii=False)
        self.process.stdin.write(self.ws.send(TextMessage(data=data)) if self.ws else (data + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params=None, timeout=60):
        thread_id=(params or {}).get('threadId')
        blocked=self.compatibility_error or self.incompatible_threads.get(thread_id)
        # A broken history index must never prevent stopping a known active turn.
        if blocked and method!='turn/interrupt':raise CompatibilityError(blocked)
        self.counter += 1
        request_id = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.write({"id": request_id, "method": method, "params": params or {}})
            try:
                return await asyncio.wait_for(future, timeout)
            except RpcError as error:
                if any(marker in str(error).lower() for marker in ('no such column', 'database disk image is malformed', 'database schema', 'database corruption')):
                    detail=('该会话' if thread_id else '该机器')+'的原生 Codex 历史数据异常，已暂停相关操作；已同步的历史仍可查看，需要先在原客户端处理。'
                    if thread_id:self.incompatible_threads[thread_id]=detail
                    else:self.compatibility_error=detail
                    raise CompatibilityError(detail) from error
                raise
        finally:
            self.pending.pop(request_id, None)

    async def _read(self):
        try:
            async for line in self._messages():
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue  # A login-shell banner is not a protocol message.
                if "method" in message:
                    if "id" in message:
                        self.spawn_task(self._server_request(message))
                    elif self.on_event:
                        # Keep protocol ordering without blocking on remote API work.
                        await self.on_event(message["method"], message.get("params", {}))
                elif message.get("id") in self.pending:
                    future = self.pending[message["id"]]
                    if not future.done():
                        if "error" in message:
                            future.set_exception(RpcError(message["error"]))
                        else:
                            future.set_result(message.get("result", {}))
        except Exception as error:
            self.stderr.append(type(error).__name__)
        finally:
            if self.handshake and not self.handshake.done():
                self.handshake.set_exception(ConnectionError("Codex WebSocket 握手失败"))
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ConnectionError("Codex 连接中断；未自动重发任务"))
            if not self.closed and self.on_disconnect:
                await self.on_disconnect()

    async def _messages(self):
        if not self.ws:
            while line := await self.process.stdout.readline():
                yield line
            return
        fragments = []
        size = 0
        while data := await self.process.stdout.read(65536):
            self.ws.receive_data(data)
            for event in self.ws.events():
                if isinstance(event, AcceptConnection):
                    if self.handshake and not self.handshake.done():
                        self.handshake.set_result(True)
                elif isinstance(event, TextMessage):
                    size += len(event.data)
                    if size > 32 * 1024 * 1024:
                        raise ValueError("Codex 返回消息超过上限")
                    fragments.append(event.data)
                    if event.message_finished:
                        yield "".join(fragments)
                        fragments, size = [], 0
                elif isinstance(event, Ping):
                    self.process.stdin.write(self.ws.send(event.response()))
                    await self.process.stdin.drain()
                elif isinstance(event, CloseConnection):
                    return

    async def _server_request(self, message):
        try:
            if not self.on_request:
                raise ValueError("该客户端没有交互处理器")
            result = await self.on_request(message["method"], message.get("params", {}))
            await self.write({"id": message["id"], "result": result})
        except Exception as error:
            with contextlib.suppress(ConnectionError, BrokenPipeError):
                await self.write({"id": message["id"], "error": {"code": -32603, "message": str(error)[:1000]}})

    async def _read_stderr(self):
        while line := await self.process.stderr.readline():
            self.stderr.append(line.decode(errors="replace").strip())

    async def close(self):
        self.closed = True
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in [self.reader, self.stderr_reader, *self.tasks]:
            if task and task is not asyncio.current_task():
                task.cancel()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError("客户端已关闭"))
