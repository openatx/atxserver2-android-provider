#!/usr/bin/env python3
# coding: utf-8
#

import argparse
import collections
import json
import os
import pprint
import re
import socket
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests
import tornado.web
from logzero import logger
from tornado import gen, websocket
from tornado.concurrent import run_on_executor
from tornado.ioloop import IOLoop
from tornado.queues import Queue
from tornado.web import RequestHandler
from tornado.websocket import WebSocketHandler, websocket_connect

from asyncadb import adb
from freeport import freeport
from utils import current_ip, fix_url, update_recursive


class SafeWebSocket(websocket.WebSocketClientConnection):
    async def write_message(self, message, binary=False):
        if isinstance(message, dict):
            message = json.dumps(message)
        return await super().write_message(message)


async def heartbeat_connect(server_url: str, provider_url: str):
    server_url = fix_url(server_url, "ws")
    provider_url = fix_url(provider_url)

    logger.info("ServerWebsocketURL: %s", server_url)
    conn = HeartbeatConnection(server_url)
    conn._server_url = server_url
    conn._provider_url = provider_url

    await conn.initialize()
    return conn


class HeartbeatConnection(object):
    """
    与atxserver2建立连接，汇报当前已经连接的设备
    """

    def __init__(self, server_url="ws://localhost:4000"):
        self._server_url = server_url
        self._provider_url = None
        self._queue = Queue()
        self._db = defaultdict(dict)

    async def initialize(self):
        self._ws = await self.connect()
        IOLoop.current().spawn_callback(self._read_until_closed)
        IOLoop.current().spawn_callback(self._drain_messages)

    async def _drain_messages(self):
        """
        - send message to server when server is alive
        - update local db
        """
        async for message in self._queue:
            if message is None:
                logger.info("Resent messages: %s", self._db)
                for _, v in self._db.items():
                    await self._ws.write_message(v)
                continue

            udid = message['udid']
            update_recursive(self._db, {udid: message})
            self._queue.task_done()

            if self._ws:
                try:
                    await self._ws.write_message(message)
                    logger.debug("websocket send: %s", message)
                except TypeError as e:
                    logger.info("websocket write_message error: %s", e)

    async def _read_until_closed(self):
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
            tornado.WebSocket connection
        """
        cnt = 0
        while True:
            try:
                ws = await self.unsafe_connect()
                cnt = 0
                return ws
            except Exception as e:
                cnt = min(30, cnt+1)
                logger.warning(
                    "WS connect error: %s, reconnect after %ds", e, cnt+1)
                await gen.sleep(cnt+1)

    async def unsafe_connect(self):
        """ 需要实现自动重连的逻辑 """
        ws = await websocket_connect(
            self._server_url + "/websocket/heartbeat")
        ws.__class__ = SafeWebSocket

        await ws.write_message({
            "command": "handshake",
            "name": "mac",
            "owner": "codeskyblue@gmail.com",
            "url": self._provider_url,
            "priority": 2,  # the large the importanter
        })

        msg = await ws.read_message()
        logger.info("WS receive: %s", msg)
        return ws

    async def device_update(self, data: dict):
        data['command'] = 'update'
        data['platform'] = 'android'

        await self._queue.put(data)

    async def healthcheck(self):
        await self._ws.write_message({"command": "ping"})
        msg = await self._ws.read_message()
        logger.debug("receive: %s", msg)
        return msg


class AndroidWorker(object):
    def __init__(self, serial: str):
        self._serial = serial
        self._procs = []
        self._current_ip = current_ip()

    async def init(self):
        """
        do forward and start proxy
        """
        logger.info("Init device: %s", self._serial)
        logger.debug("forward atx-agent")
        self._atx_proxy_port = await self.proxy_device_port(7912)
        self._whatsinput_port = await self.proxy_device_port(6677)

        port = self._adb_remote_port = freeport.get()
        logger.debug("adbkit start, port %d", port)
        adbkit_path = os.path.abspath('node_modules/.bin/adbkit')
        p2 = subprocess.Popen([
            adbkit_path, 'usb-device-to-tcp', '-p', str(self._adb_remote_port), self._serial])
        self._procs.append(p2)

    def addrs(self):
        def port2addr(port):
            return self._current_ip + ":"+str(port)

        return {
            "deviceAddress": port2addr(self._atx_proxy_port),
            "remoteConnectAddress": port2addr(self._adb_remote_port),
            "whatsinputAddress": port2addr(self._whatsinput_port),
        }

    def adb_call(self, *args):
        """ call adb with serial """
        cmds = ['adb', '-s', self._serial] + list(args)
        logger.debug("RUN: %s", subprocess.list2cmdline(cmds))
        return subprocess.call(cmds)

    def adb_forward_list(self):
        pass

    async def adb_forward_to_any(self, remote: str) -> int:
        """ FIXME(ssx): not finished yet """
        # if already forwarded, just return
        async for f in adb.forward_list():
            if f.serial == self._serial:
                if f.remote == remote and f.local.startswith("tcp:"):
                    return int(f.local[4:])

        local_port = freeport.get()
        await adb.forward(self._serial, 'tcp:{}'.format(local_port), remote)
        return local_port

    async def proxy_device_port(self, device_port: int) -> int:
        """ reverse-proxy device:port to *:port """
        local_port = await self.adb_forward_to_any("tcp:"+str(device_port))
        listen_port = freeport.get()
        logger.debug("tcpproxy.js start *:%d -> %d",
                     listen_port, local_port)
        p = subprocess.Popen(
            ['node', 'tcpproxy.js',
             str(listen_port), 'localhost', str(local_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._procs.append(p)
        return listen_port

    async def properties(self):
        brand = await adb.shell(self._serial, "getprop ro.product.brand")
        version = await adb.shell(self._serial, "getprop ro.build.version.release")

        return {
            "serial": self._serial,
            "brand": brand.strip(),
            "version": version.strip(),
        }

    async def reset(self):
        self.close()
        await adb.shell(self._serial, "input keyevent HOME")
        await self.init()

    def wait(self):
        for p in self._procs:
            p.wait()

    def close(self):
        for p in self._procs:
            p.terminate()
        self._procs = []


hbconn = None
udid2worker = {}


class ColdHandler(tornado.web.RequestHandler):

    def get(self):
        self.write("Hello ATXServer2")

    async def delete(self, udid):
        """ 设备清理 """
        logger.info("Receive colding request for %s", udid)
        if udid not in udid2worker:
            return

        worker = udid2worker[udid]

        logger.info("Origin addrs: %s", worker.addrs())
        await worker.reset()
        logger.info("Current addrs: %s", worker.addrs())
        await hbconn.device_update({
            "udid": udid,
            "colding": False,
            "provider": worker.addrs(),
        })


def make_app():
    app = tornado.web.Application([
        (r"/([^/]+)", ColdHandler),
    ])
    return app


async def async_main(server_url: str):
    global hbconn

    # start local server
    listen_port = 3500
    provider_url = "http://"+current_ip() + ":" + str(listen_port)
    app = make_app()
    app.listen(listen_port)
    logger.info("ProviderURL: %s", provider_url)

    # connect to atxserver2
    hbconn = await heartbeat_connect(server_url, provider_url)

    serial2udid = {}
    udid2serial = {}

    async for event in adb.track_devices():
        print(repr(event))
        # udid = event.serial  # FIXME(ssx): fix later
        if event.present:
            try:
                worker = AndroidWorker(event.serial)
                await worker.init()
                udid = serial2udid[event.serial] = event.serial
                udid2serial[udid] = event.serial
                udid2worker[udid] = worker

                await hbconn.device_update({
                    # "private": False, # TODO
                    "udid": udid,
                    "platform": "android",
                    "colding": False,
                    "provider": worker.addrs(),
                    "properties": await worker.properties(),
                })
                logger.info("Device:%s is ready", event.serial)
            except RuntimeError:
                logger.warning("Device:%s initialize failed", event.serial)
        else:
            udid = serial2udid[event.serial]
            if udid in udid2worker:
                udid2worker[udid].close()

            await hbconn.device_update({
                "udid": udid,
                "provider": None,  # not present
            })


async def test_asyncadb():
    devices = await adb.devices()
    print(devices)
    # output = await adb.shell("3578298f", "getprop ro.product.brand")
    # print(output)
    version = await adb.server_version()
    print("ServerVersion:", version)

    await adb.forward_remove()
    await adb.forward("3578298f", "tcp:8888", "tcp:7912")
    async for f in adb.forward_list():
        print(f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-s', '--server', default='localhost:4000', help='server address')
    parser.add_argument(
        '-t', '--test', action="store_true", help="run test code")
    args = parser.parse_args()

    if args.test:
        IOLoop.current().run_sync(test_asyncadb)
    else:
        IOLoop.current().run_sync(lambda: async_main(args.server))
    # IOLoop.current().run_sync(watch_all)
    # IOLoop.current().run_sync(main)
