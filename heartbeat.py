# coding: utf-8
#
# updated: 2019/03/13
# updated: 2019/04/11 codeskyblue: add owner


import json
import re
from collections import defaultdict

from logzero import logger
from tornado.ioloop import IOLoop
from tornado.queues import Queue
from tornado import websocket
from tornado import gen

from core.utils import update_recursive, current_ip


async def heartbeat_connect(
        server_url: str,
        self_url: str = "",
        secret: str = "",
        platform: str = "android",
        priority: int = 2,
        **kwargs):
    addr = server_url.replace("http://", "").replace("/", "")
    url = "ws://" + addr + "/websocket/heartbeat"

    hbc = HeartbeatConnection(
        url, secret, platform=platform, priority=priority, **kwargs)
    hbc._provider_url = self_url
    await hbc.open()
    return hbc


class SafeWebSocket(websocket.WebSocketClientConnection):
    async def write_message(self, message, binary=False):
        if isinstance(message, dict):
            message = json.dumps(message)
        return await super().write_message(message)


class HeartbeatConnection(object):
    """
    与atxserver2建立连接，汇报当前已经连接的设备
    """

    def __init__(self,
                 url="ws://localhost:4000/websocket/heartbeat",
                 secret='',
                 platform='android',
                 priority=2,
                 owner=None):
        self._server_ws_url = url
        self._provider_url = None
        self._name = "pyclient"
        self._owner = owner
        self._secret = secret

        self._platform = platform
        self._priority = priority
        self._queue = Queue()
        self._db = defaultdict(dict)

    async def open(self):
        self._ws = await self.connect()
        IOLoop.current().spawn_callback(self._drain_ws_message)
        IOLoop.current().spawn_callback(self._drain_queue)

    async def _drain_queue(self):
        """
        Logic:
            - send message to server when server is alive
            - update local db
        """
        while True:
            message = await self._queue.get()
            if message is None:
                logger.info("Resent messages: %s", self._db)
                for _, v in self._db.items():
                    await self._ws.write_message(v)
                continue

            if 'udid' in message:  # ping消息不包含在裡面
                udid = message['udid']
                update_recursive(self._db, {udid: message})
            self._queue.task_done()

            if self._ws:
                try:
                    await self._ws.write_message(message)
                    logger.debug("websocket send: %s", message)
                except TypeError as e:
                    logger.info("websocket write_message error: %s", e)

    async def _drain_ws_message(self):
        while True:
            message = await self._ws.read_message()
            logger.debug("WS read message: %s", message)
            if message is None:
                self._ws = None
                logger.warning("WS closed")
                self._ws = await self.connect()
                await self._queue.put(None)
            logger.info("WS receive message: %s", message)

    async def connect(self):
        """
        Returns:
            tornado.WebSocketConnection
        """
        cnt = 0
        while True:
            try:
                ws = await self._connect()
                cnt = 0
                return ws
            except Exception as e:
                cnt = min(30, cnt + 1)
                logger.warning("WS connect error: %s, reconnect after %ds", e,
                               cnt + 1)
                await gen.sleep(cnt + 1)

    async def _connect(self):
        ws = await websocket.websocket_connect(self._server_ws_url)
        ws.__class__ = SafeWebSocket

        await ws.write_message({
            "command": "handshake",
            "name": self._name,
            "owner": self._owner,
            "secret": self._secret,
            "url": self._provider_url,
            "priority": self._priority,  # the large the importanter
        })

        msg = await ws.read_message()
        logger.info("WS receive: %s", msg)
        return ws

    async def device_update(self, data: dict):
        """
        Args:
            data (dict) should contains keys
            - provider (dict: optional)
            - coding (bool: optional)
            - properties (dict: optional)
        """
        data['command'] = 'update'
        data['platform'] = self._platform

        await self._queue.put(data)

    async def ping(self):
        await self._ws.write_message({"command": "ping"})


async def async_main():
    hbc = await heartbeat_connect(
        "ws://localhost:4000/websocket/heartbeat", "123456", platform='apple')
    await hbc.device_update({
        "udid": "kj3rklzvlkjsdfawefw",
        "colding": False,
        "provider": {
            "wdaUrl":
            "http://localhost:5600"  # "http://"+current_ip()+":18000/127.0.0.1:8100"
        }
    })
    while True:
        await gen.sleep(5)
        # await hbc.ping()


if __name__ == "__main__":
    IOLoop.current().run_sync(async_main)
