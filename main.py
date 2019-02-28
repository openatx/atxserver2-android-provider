#!/usr/bin/env python3
# coding: utf-8
#

import json
import os
import pprint
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


class ServerConnection(object):
    def __init__(self, server_addr="localhost:4000"):
        self._server_addr = server_addr
        self._ws = None

    async def safe_connect(self):
        """ 自带重连逻辑 """
        await self.connect()

    async def connect(self):
        """ 需要实现自动重连的逻辑 """
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

    async def write_message(self, message: dict):
        assert "command" in message
        logger.debug("SEND to server: %s", pprint.pformat(message))

        return await self._ws.write_message(message)

    async def device_update(self, udid: str, data: dict):
        data["platform"] = "android"
        data["udid"] = udid
        address = data.pop("address", None)

        await self.write_message({
            "command": "update",
            "address": address,  # atx-agent listen address
            "data": data
        })

    async def came_online(self, udid: str, data: dict):
        data["platform"] = "android"
        data["udid"] = udid
        data["present"] = True
        address = data.pop("address", None)

        await self.write_message({
            "command": "update",
            "address": address,  # atx-agent listen address
            "data": data
        })

    async def went_offline(self, udid: str):
        pass

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
        port = self._adb_forward_port = freeport.get()
        logger.info("adb foward tcp:%d -> tcp:7912", port)
        subprocess.call(['adb', 'forward', 'tcp:{}'.format(port), 'tcp:7912'])

        port = self._atx_proxy_port = freeport.get()
        logger.info("tcpproxy.js start *:%d -> %d",
                    port, self._adb_forward_port)
        p1 = subprocess.Popen(
            ['node', 'tcpproxy.js',
             str(self._atx_proxy_port), 'localhost', str(self._adb_forward_port)])
        self._procs.append(p1)

        port = self._adb_remote_port = freeport.get()
        logger.info("adbkit start, port %d", port)
        p2 = subprocess.Popen([
            os.path.abspath('node_modules/.bin/adbkit'), 'usb-device-to-tcp', '-p', str(self._adb_remote_port), self._serial])
        self._procs.append(p2)

    def atx_address(self):
        return self._current_ip + ":" + str(self._atx_proxy_port)

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


providers = {}


class WebSocketError(Exception):
    """ websocket connection exception """


async def watch_devices():
    async for event in adb.track_devices():
        print(event)
        raise WebSocketError("dev")


async def watch_websocket():
    await gen.sleep(1)
    print("Done")
    raise WebSocketError("manual")


async def run():
    server = await ServerConnection().connect()
    devices = await adb.devices()
    for d in devices:
        logger.info("%s", d)
        if d.status != "device":
            continue
        w = AndroidWorker(d.serial)

        await server.came_online("abcdefg", w.atx_address(), {
            "udid": "abcdefg",
            "private": False,
            "properties": w.properties(),
        })
        w.wait()
        # gen.with_timeout(10, server.read_message)
        server.healthcheck()

        # p.wait()


# async def main():
#     try:
#         await run()
#     except KeyboardInterrupt as e:
#         logger.info("Ctrl+C interrupt catched: %s", e)
#         for p in providers.values():
#             p.close()


async def _main():
    server = await ServerConnection().connect()

    udids = {}
    async for event in adb.track_devices():
        print(repr(event))
        # udid = event.serial  # FIXME(ssx): fix later
        if event.present:
            try:
                worker = AndroidWorker(event.serial)
                udid = udids[event.serial] = event.serial
                await server.device_update(udid, {
                    "present": True,
                    "private": False,
                    "address": worker.atx_address(),
                    "properties": await worker.properties(),
                })
            except RuntimeError:
                logger.warning("device:%s initialize failed", event.serial)
        else:
            udid = udids[event.serial]
            await server.device_update(udid, {
                "present": False,
                "private": False,
                "address": worker.atx_address(),
                "properties": {
                    "serial": event.serial,
                    "brand": 'XiaoMi',
                    "version": "7.0.1",
                }
            })
        logger.info("initial finished %s", event.serial)


async def test_asyncadb():
    devices = await adb.devices()
    print(devices)
    output = await adb.shell("3578298f", "getprop ro.product.brand")
    print(output)


if __name__ == '__main__':
    # IOLoop.current().run_sync(test_asyncadb)
    IOLoop.current().run_sync(_main)
    # IOLoop.current().run_sync(watch_all)
    # IOLoop.current().run_sync(main)
