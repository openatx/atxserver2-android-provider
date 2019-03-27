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
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import requests
import tornado.web
from logzero import logger
from tornado import gen, websocket
from tornado.concurrent import run_on_executor
from tornado.ioloop import IOLoop
from tornado.web import RequestHandler
from tornado.websocket import WebSocketHandler, websocket_connect

import apkutils
from asyncadb import adb
from device import AndroidDevice, STATUS_FAIL, STATUS_INIT, STATUS_OKAY
from heartbeat import heartbeat_connect
from utils import current_ip, fix_url, id_generator, update_recursive

hbconn = None
udid2device = {}
secret = id_generator(10)


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
            if package_name:
                logger.debug("package name: %s", package_name)
                subprocess.run(
                    ["adb", "-s", serial, "uninstall", package_name])
            p = subprocess.Popen(["adb", "-s", serial, "install", "-r", "-t", apk_path],
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
            return {"success": False, "status": 500, "description": str(e)}
        finally:
            os.unlink(apk_path)

    @gen.coroutine
    def post(self, udid=None):
        udid = udid or self.get_argument("udid")
        device = udid2device[udid]
        url = self.get_argument("url")
        ret = yield self.app_install(device.serial, url)
        self.set_status(ret.get("status", 400))  # default bad request
        self.write(ret)


class ColdingHandler(tornado.web.RequestHandler):
    async def post(self, udid=None):
        """ 设备清理 """
        udid = udid or self.get_argument("udid")
        logger.info("Receive colding request for %s", udid)
        request_secret = self.get_argument("secret")
        if secret != request_secret:
            logger.warning("secret not match, expect %s, got %s",
                           secret, request_secret)
            return

        if udid not in udid2device:
            return

        device = udid2device[udid]
        await device.reset()
        await hbconn.device_update({
            "udid": udid,
            "colding": False,
            "provider": device.addrs(),
        })
        self.write({"success": True, "description": "Device colded"})


def make_app():
    app = tornado.web.Application([
        (r"/devices/([^/]+)/cold", ColdingHandler),
        (r"/devices/([^/]+)/app/install", AppHandler),
        # POST /app/install?udid=xxxxx url==http://....
        (r"/app/install", AppHandler),
        # POST /cold?udid=xxxxx
        (r"/cold", ColdingHandler),
    ])
    return app


async def device_watch():
    serial2udid = {}
    udid2serial = {}

    def callback(udid: str, status: str):
        if status == STATUS_OKAY:
            print("Good")
        else:
            print("--Status", status)
        pass

    async for event in adb.track_devices():
        logger.debug("%s", event)
        # udid = event.serial  # FIXME(ssx): fix later
        if event.present:
            try:
                udid = serial2udid[event.serial] = event.serial
                udid2serial[udid] = event.serial

                device = AndroidDevice(event.serial, partial(callback, udid))

                await device.init()
                # try:
                # except Exception as e:
                #     logger.warning("Init device error: %s", e)
                #     continue

                udid2device[udid] = device

                await hbconn.device_update({
                    # "private": False, # TODO
                    "udid": udid,
                    "platform": "android",
                    "colding": False,
                    "provider": device.addrs(),
                    "properties": await device.properties(),
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

    await device_watch()


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
    try:
        IOLoop.current().run_sync(async_main)
    except KeyboardInterrupt:
        logger.info("Interrupt catched")
