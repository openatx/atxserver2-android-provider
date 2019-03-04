#!/usr/bin/env python3
# coding: utf-8
#

import argparse
import collections
import json
import os
import pprint
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

import asyncadb
from freeport import freeport

adb = asyncadb.Adb()


class SafeWebSocket(websocket.WebSocketClientConnection):
    async def write_message(self, message, binary=False):
        if isinstance(message, dict):
            message = json.dumps(message)
        return await super().write_message(message)


def current_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def update_recursive(d: dict, u: dict) -> dict:
    for k, v in u.items():
        if isinstance(v, collections.Mapping):
            d[k] = update_recursive(d.get(k, {}), v)
        else:
            d[k] = v
    return d


class ServerConnection(object):
    def __init__(self, server_addr="localhost:4000"):
        self._server_addr = server_addr
        self._queue = Queue()
        self._db = defaultdict(dict)

    async def initialize(self):
        self._ws = await self.connect()
        IOLoop.current().spawn_callback(self._read_until_closed)
        IOLoop.current().spawn_callback(self._drain_messages)

    async def _drain_messages(self):
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
            "ws://" + self._server_addr + "/websocket/heartbeat")
        ws.__class__ = SafeWebSocket

        await ws.write_message({
            "command": "handshake",
            "name": "mac",
            "owner": "codeskyblue@gmail.com",
            "priority": 2
        })  # priority the large the importanter

        msg = await ws.read_message()
        logger.info("WS receive: %s", msg)
        return ws

    async def write_message(self, message: dict):
        await self._queue.put(message)

    async def device_update(self, data: dict):
        data['command'] = 'update'
        data['platform'] = 'android'

        await self.write_message(data)

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
        self.initialize()

    def initialize(self):
        """
        do forward and start proxy
        """
        logger.info("Init device: %s", self._serial)
        logger.debug("forward atx-agent")
        self._atx_proxy_port = self.proxy_device_port(7912)
        self._whatsinput_port = self.proxy_device_port(6677)

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

    def proxy_device_port(self, device_port: int) -> int:
        """ reverse-proxy device:port to *:port """
        local_port = freeport.get()
        logger.debug("adb foward tcp:%d -> tcp:%d", local_port, device_port)

        self.adb_call('forward', 'tcp:{}'.format(
            local_port), 'tcp:{}'.format(device_port))

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

    def wait(self):
        for p in self._procs:
            p.wait()

    def close(self):
        for p in self._procs:
            p.terminate()


async def async_main(server_addr: str = ''):
    server = ServerConnection(server_addr)
    await server.initialize()

    udids = {}
    async for event in adb.track_devices():
        print(repr(event))
        # udid = event.serial  # FIXME(ssx): fix later
        if event.present:
            try:
                worker = AndroidWorker(event.serial)
                udid = udids[event.serial] = event.serial
                await server.device_update({
                    # "private": False, # TODO
                    "udid": udid,
                    "platform": "android",
                    "provider": worker.addrs(),
                    "properties": await worker.properties(),
                })
            except RuntimeError:
                logger.warning("device:%s initialize failed", event.serial)
        else:
            udid = udids[event.serial]
            await server.device_update({
                "udid": udid,
                "provider": None,  # not present
            })
        logger.info("initial finished %s", event.serial)


async def test_asyncadb():
    devices = await adb.devices()
    print(devices)
    output = await adb.shell("3578298f", "getprop ro.product.brand")
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-s', '--server', default='localhost:4000', help='server address')
    args = parser.parse_args()

    # IOLoop.current().run_sync(test_asyncadb)
    IOLoop.current().run_sync(lambda: async_main(args.server))
    # IOLoop.current().run_sync(watch_all)
    # IOLoop.current().run_sync(main)
