#!/usr/bin/env python3
# coding: utf-8
#

import os
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor


import requests
import tornado.web
from logzero import logger
from tornado import gen, websocket
from tornado.concurrent import run_on_executor
from tornado.ioloop import IOLoop

from tornado.web import RequestHandler
from tornado.websocket import WebSocketHandler

import asyncadb


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


class ServerConnection(object):
    def __init__(self, server_addr="localhost:4000"):
        self._server_addr = server_addr
        self._ws = None

    async def connect(self):
        ws = self._ws = await websocket.websocket_connect("ws://" + self._server_addr + "/websocket/heartbeat")
        ws.__class__ = SafeWebSocket

        await ws.write_message({
            "command": "handshake",
            "name": "mac",
            "owner": "codeskyblue@gmail.com",
            "priority": 2
        })  # priority the large the importanter

        msg = await ws.read_message()
        logger.info("read websocket: %s", msg)
        return self

    async def write_message(self, message):
        ip = current_ip()
        logger.debug("current IP: %s", ip)

        await self._ws.write_message({
            "command": "update",
            "address": ip+":8110",  # atx-agent listen address
            "data": {
                "udid": "abcdefg",
                "platform": "android",
                "present": True,
                "private": False,
                "properties": {
                    "serial": "xyz234567890",
                    "brand": 'Huawei',
                    "version": "7.0.1",
                }
            }
        })

    async def ping(self):
        await self._ws.write_message({"command": "ping"})
        msg = await self._ws.read_message()
        logger.debug("receive: %s", msg)


class FreePort(object):
    def __init__(self):
        self._start = 20000
        self._end = 40000
        self._now = self._start

    def get(self):
        pass


adb = asyncadb.ADB()


class DeviceProvider(object):
    def __init__(self, serial: str):
        self._serial = serial
        self._procs = []
        self.start_all_service()

    def start_all_service(self):
        logger.info("adb foward 8000 -> 7912")
        subprocess.call(['adb', 'forward', 'tcp:8000', 'tcp:7912'])

        logger.info("tcpproxy.js start, port 8110 -> 8000")
        p1 = subprocess.Popen(
            ['node', 'tcpproxy.js', '8110', 'localhost', '8000'])
        self._procs.append(p1)
        # logger.info("tcpproxy.js end")

        logger.info("adbkit start, port 5555")
        p2 = subprocess.Popen([
            os.path.abspath('node_modules/.bin/adbkit.cmd'), 'usb-device-to-tcp', '-p', '5555', self._serial])
        self._procs.append(p2)
        # logger.info("adbkit end")

    def wait(self):
        for p in self._procs:
            p.wait()

    def close(self):
        for p in self._procs:
            p.terminate()


providers = {}


async def run():
    server = await ServerConnection().connect()
    devices = await adb.devices()
    for d in devices:
        logger.info("%s", d)
        if d.status != "device":
            continue
        p = DeviceProvider(d.serial)
        providers[d.serial] = p
        await server.write_message({})
        p.wait()


async def main():
    try:
        await run()
    except KeyboardInterrupt as e:
        logger.info("Ctrl+C interrupt catched: %s", e)
        for p in providers.values():
            p.close()


if __name__ == '__main__':
    IOLoop.current().run_sync(main)
