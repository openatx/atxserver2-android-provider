#!/usr/bin/env python3
# coding: utf-8
#

import argparse
import collections
import json
import os
import pprint
import re
import shutil
import socket
import subprocess
import tempfile
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

import apkutils
from adbutils import adb as adbclient
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

    @property
    def serial(self):
        return self._serial

    async def init(self):
        """
        do forward and start proxy
        """
        logger.info("Init device: %s", self._serial)

        self._init_apks()
        self._init_mini_captouch()

        logger.debug("start atx-agent")
        await adb.shell(self._serial, "/data/local/tmp/atx-agent server -d")
        logger.debug("forward atx-agent")

        await self._init_forwards()

    def _init_mini_captouch(self):
        pass

    def _init_apks(self):
        device = adbclient.device_with_serial(self._serial)
        device.install("vendor/WhatsInput_v1.0_apkpure.com.apk")

    async def _init_forwards(self):
        self._atx_proxy_port = await self.proxy_device_port(7912)
        self._whatsinput_port = await self.proxy_device_port(6677)

        port = self._adb_remote_port = freeport.get()
        logger.debug("adbkit start, port %d", port)

        self.run_background([
            'node', 'node_modules/adbkit/bin/adbkit', 'usb-device-to-tcp', '-p', str(self._adb_remote_port), self._serial])

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
        self.run_background(['node', 'tcpproxy.js',
                             str(listen_port), 'localhost', str(local_port)], silent=True)
        return listen_port

    def run_background(self, *args, **kwargs):
        silent = kwargs.pop('silent', False)
        if silent:
            kwargs['stdout'] = subprocess.DEVNULL
            kwargs['stderr'] = subprocess.DEVNULL
        p = subprocess.Popen(*args, **kwargs)
        self._procs.append(p)
        return p

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


class CorsMixin(object):
    CORS_ORIGIN = '*'
    CORS_METHODS = 'GET,POST,OPTIONS'
    CORS_CREDENTIALS = True
    CORS_HEADERS = "x-requested-with,authorization"

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", self.CORS_ORIGIN)
        self.set_header("Access-Control-Allow-Headers", self.CORS_HEADERS)
        self.set_header('Access-Control-Allow-Methods', self.CORS_METHODS)

    def options(self):
        # no body
        self.set_status(204)
        self.finish()


class AppHandler(CorsMixin, tornado.web.RequestHandler):
    executor = ThreadPoolExecutor(4)

    @run_on_executor(executor='executor')
    def app_install(self, serial: str, url: str):
        try:
            r = requests.get(url, stream=True)
            if r.status_code != 200:
                return {"success": False, "description": r.reason}
        except Exception as e:
            return {"success": False, "description": str(e)}

        # Windows not support tempfile.NamedTemporyFile
        apk_path = tempfile.mktemp(
            suffix=".apk", prefix="tmpfile-", dir=os.getcwd())
        apk_path = os.path.relpath(apk_path)
        logger.debug("temp apk path: %s", apk_path)
        try:
            with open(apk_path, "wb") as tfile:
                content_length = int(r.headers.get("content-length", 0))
                if content_length:
                    for chunk in r.iter_content(chunk_size=40960):
                        tfile.write(chunk)
                else:
                    shutil.copyfileobj(r.raw, tfile)

            apk = apkutils.APK(apk_path)
            package_name = apk.manifest and apk.manifest.package_name
            logger.debug("package name: %s", package_name)

            p = subprocess.Popen(["adb", "-s", serial, "install", "-r", apk_path],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = ""
            for line in p.stdout:
                line = line.decode('utf-8')
                print(line)
                output += line
            success = "Success" in output
            exit_code = p.wait()

            if not success:
                return {"success": False, "description": output}
            if package_name:  # sometimes package_name can not retrived
                subprocess.run(["adb", "-s", serial, "shell", "monkey", '-p',
                                package_name, "-c", "android.intent.category.LAUNCHER", "1"])
            return {"success": success,
                    "packageName": package_name,
                    "return": exit_code,
                    "output": output}
        except Exception as e:
            return {"success": False, "description": str(e)}
        finally:
            os.unlink(apk_path)

    @gen.coroutine
    def post(self, udid):
        device = udid2device[udid]
        url = self.get_argument("url")
        ret = yield self.app_install(device.serial, url)
        self.write(ret)


class ColdingHandler(tornado.web.RequestHandler):
    async def post(self, udid):
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
        self.write({"success": True, "description": "Device colded"})


def make_app():
    app = tornado.web.Application([
        (r"/devices/([^/]+)/cold", ColdingHandler),
        (r"/devices/([^/]+)/app/install", AppHandler)
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
