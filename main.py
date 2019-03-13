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
from heartbeat import heartbeat_connect
from utils import current_ip, fix_url, id_generator, update_recursive

hbconn = None
udid2device = {}
secret = id_generator(10)


class AndroidDevice(object):
    def __init__(self, serial: str):
        self._serial = serial
        self._procs = []
        self._current_ip = current_ip()

    async def init(self):
        """
        do forward and start proxy
        """
        logger.info("Init device: %s", self._serial)
        logger.debug("start atx-agent")
        await adb.shell(self._serial, "/data/local/tmp/atx-agent server -d")
        logger.debug("forward atx-agent")
        self._atx_proxy_port = await self.proxy_device_port(7912)
        self._whatsinput_port = await self.proxy_device_port(6677)

        port = self._adb_remote_port = freeport.get()
        logger.debug("adbkit start, port %d", port)

        p2 = subprocess.Popen([
            'node', 'node_modules/adbkit/bin/adbkit', 'usb-device-to-tcp', '-p', str(self._adb_remote_port), self._serial])
        self._procs.append(p2)

    def addrs(self):
        def port2addr(port):
            return self._current_ip + ":"+str(port)

        return {
            "atxAgentAddress": port2addr(self._atx_proxy_port),
            "remoteConnectAddress": port2addr(self._adb_remote_port),
            "whatsInputAddress": port2addr(self._whatsinput_port),
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
        """ 設備使用完后的清理工作 """
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


class ColdHandler(tornado.web.RequestHandler):

    def get(self):
        self.write("Hello ATXServer2")

    async def delete(self, udid):
        """ 设备清理 """
        logger.info("Receive colding request for %s", udid)
        request_secret = self.get_argument("secret")
        if secret != request_secret:
            logger.warning("secret not match, expect %s, got %s",
                           secret, request_secret)
            return

        if udid not in udid2device:
            return

        worker = udid2device[udid]
        await worker.reset()
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


async def async_main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '-s', '--server', default='localhost:4000', help='server address')
    parser.add_argument(
        '-t', '--test', action="store_true", help="run test code")
    parser.add_argument(
        '-p', '--port', type=int, default=3500, help='listen port')
    args = parser.parse_args()

    # start local server
    provider_url = "http://"+current_ip() + ":" + str(args.port)
    app = make_app()
    app.listen(args.port)
    logger.info("ProviderURL: %s", provider_url)

    # connect to atxserver2
    global hbconn
    hbconn = await heartbeat_connect(args.server, secret=secret, self_url=provider_url)

    serial2udid = {}
    udid2serial = {}

    async for event in adb.track_devices():
        print(repr(event))
        # udid = event.serial  # FIXME(ssx): fix later
        if event.present:
            try:
                worker = AndroidDevice(event.serial)
                await worker.init()
                udid = serial2udid[event.serial] = event.serial
                udid2serial[udid] = event.serial
                udid2device[udid] = worker

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
            if udid in udid2device:
                udid2device[udid].close()

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
    # logger.info("provider secret: %s", secret)
    # if args.test:
    #     IOLoop.current().run_sync(test_asyncadb)

    try:
        IOLoop.current().run_sync(async_main)
    except KeyboardInterrupt:
        logger.info("Interrupt catched")
