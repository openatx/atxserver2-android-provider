#!/usr/bin/env python3
# coding: utf-8
#

import argparse
import collections
import glob
import hashlib
import json
import os
import pprint
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import apkutils2 as apkutils
import requests
import tornado.web
from logzero import logger
from tornado import gen, websocket
from tornado.concurrent import run_on_executor
from tornado.ioloop import IOLoop
from tornado.web import RequestHandler
from tornado.websocket import WebSocketHandler, websocket_connect

import adbutils
from adbutils import adb as adbclient
from asyncadb import adb
from device import STATUS_FAIL, STATUS_INIT, STATUS_OKAY, AndroidDevice
from heartbeat import heartbeat_connect
from core.utils import current_ip, fix_url, id_generator, update_recursive
from core import fetching
import uiautomator2 as u2
import settings

__curdir__ = os.path.dirname(os.path.abspath(__file__))
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


class InstallError(Exception):
    def __init__(self, stage: str, reason):
        self.stage = stage
        self.reason = reason


def app_install_local(serial: str, apk_path: str, launch: bool = False) -> str:
    """
    install apk to device

    Returns:
        package name

    Raises:
        AdbInstallError, FileNotFoundError
    """
    # 解析apk文件
    device = adbclient.device(serial)
    try:
        apk = apkutils.APK(apk_path)
    except apkutils.apkfile.BadZipFile:
        raise InstallError("ApkParse", "Bad zip file")

    # 提前将重名包卸载
    package_name = apk.manifest.package_name
    pkginfo = device.package_info(package_name)
    if pkginfo:
        logger.debug("uninstall: %s", package_name)
        device.uninstall(package_name)

    # 解锁手机，防止锁屏
    # ud = u2.connect_usb(serial)
    # ud.open_identify()
    try:
        # 推送到手机
        dst = "/data/local/tmp/tmp-%d.apk" % int(time.time() * 1000)
        logger.debug("push %s %s", apk_path, dst)
        device.sync.push(apk_path, dst)
        logger.debug("install-remote %s", dst)
        # 调用pm install安装
        device.install_remote(dst)
    except adbutils.errors.AdbInstallError as e:
        raise InstallError("install", e.output)
    # finally:
    # 停止uiautomator2服务
    # logger.debug("uiautomator2 stop")
    # ud.session().press("home")
    # ud.service("uiautomator").stop()

    # 启动应用
    if launch:
        logger.debug("launch %s", package_name)
        device.app_start(package_name)
    return package_name


class AppHandler(CorsMixin, tornado.web.RequestHandler):
    _install_executor = ThreadPoolExecutor(4)
    _download_executor = ThreadPoolExecutor(1)

    def cache_filepath(self, text: str) -> str:
        m = hashlib.md5()
        m.update(text.encode('utf-8'))
        return "cache-" + m.hexdigest()

    @run_on_executor(executor="_download_executor")
    def cache_download(self, url: str) -> str:
        """ download with local cache """
        target_path = self.cache_filepath(url)
        logger.debug("Download %s to %s", url, target_path)

        if os.path.exists(target_path):
            logger.debug("Cache hited")
            return target_path

        # TODO: remove last
        for fname in glob.glob("cache-*"):
            logger.debug("Remove old cache: %s", fname)
            os.unlink(fname)

        tmp_path = target_path + ".tmp"
        r = requests.get(url, stream=True)
        r.raise_for_status()

        with open(tmp_path, "wb") as tfile:
            content_length = int(r.headers.get("content-length", 0))
            if content_length:
                for chunk in r.iter_content(chunk_size=40960):
                    tfile.write(chunk)
            else:
                shutil.copyfileobj(r.raw, tfile)

        os.rename(tmp_path, target_path)
        return target_path

    @run_on_executor(executor='_install_executor')
    def app_install_url(self, serial: str, apk_path: str, **kwargs):
        pkg_name = app_install_local(serial, apk_path, **kwargs)
        return {
            "success": True,
            "description": "Success",
            "packageName": pkg_name,
        }

    async def post(self, udid=None):
        udid = udid or self.get_argument("udid")
        device = udid2device[udid]
        url = self.get_argument("url")
        launch = self.get_argument("launch",
                                   "false") in ['true', 'True', 'TRUE', '1']

        try:
            apk_path = await self.cache_download(url)
            ret = await self.app_install_url(device.serial,
                                             apk_path,
                                             launch=launch)
            self.write(ret)
        except InstallError as e:
            self.set_status(400)
            self.write({
                "success": False,
                "description": "{}: {}".format(e.stage, e.reason)
            })
        except Exception as e:
            self.set_status(500)
            self.write(str(e))


class ColdingHandler(tornado.web.RequestHandler):
    async def post(self, udid=None):
        """ 设备清理 """
        udid = udid or self.get_argument("udid")
        logger.info("Receive colding request for %s", udid)
        request_secret = self.get_argument("secret")
        if secret != request_secret:
            logger.warning("secret not match, expect %s, got %s", secret,
                           request_secret)
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
        (r"/app/install", AppHandler),
        (r"/cold", ColdingHandler),
    ])
    return app


async def device_watch(allow_remote: bool = False):
    serial2udid = {}
    udid2serial = {}

    def callback(udid: str, status: str):
        if status == STATUS_OKAY:
            print("Good")

    async for event in adb.track_devices():
        logger.debug("%s", event)
        # udid = event.serial  # FIXME(ssx): fix later
        if not allow_remote:
            if re.match(r"(\d+)\.(\d+)\.(\d+)\.(\d+):(\d+)", event.serial):
                logger.debug("Skip remote device: %s", event)
                continue
        if event.present:
            try:
                udid = serial2udid[event.serial] = event.serial
                udid2serial[udid] = event.serial

                device = AndroidDevice(event.serial, partial(callback, udid))

                await device.init()
                await device.open_identify()

                udid2device[udid] = device

                await hbconn.device_update({
                    # "private": False, # TODO
                    "udid": udid,
                    "platform": "android",
                    "colding": False,
                    "provider": device.addrs(),
                    "properties": await device.properties(),
                })  # yapf: disable
                logger.info("Device:%s is ready", event.serial)
            except RuntimeError:
                logger.warning("Device:%s initialize failed", event.serial)
            except Exception as e:
                logger.error("Unknown error: %s", e)
                import traceback
                traceback.print_exc()
        else:
            udid = serial2udid[event.serial]
            if udid in udid2device:
                udid2device[udid].close()
                udid2device.pop(udid, None)

            await hbconn.device_update({
                "udid": udid,
                "provider": None,  # not present
            })


async def async_main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    # yapf: disable
    parser.add_argument('-s', '--server', default='localhost:4000', help='server address')
    parser.add_argument("--allow-remote", action="store_true", help="allow remote connect device")
    parser.add_argument('-t', '--test', action="store_true", help="run test code")
    parser.add_argument('-p', '--port', type=int, default=3500, help='listen port')
    parser.add_argument("--atx-agent-version", default=u2.version.__atx_agent_version__, help="set atx-agent version")
    parser.add_argument("--owner", type=str, help="provider owner email")
    parser.add_argument("--owner-file", type=argparse.FileType("r"), help="provider owner email from file")
    args = parser.parse_args()
    # yapf: enable

    settings.atx_agent_version = args.atx_agent_version

    owner_email = args.owner
    if args.owner_file:
        with args.owner_file as file:
            owner_email = file.read().strip()
    logger.info("Owner: %s", owner_email)

    if args.test:
        for apk_name in ("cloudmusic.apk", ):  # , "apkinfo.exe"):
            apk_path = "testdata/" + apk_name
            logger.info("Install %s", apk_path)
            # apk_path = r"testdata/cloudmusic.apk"
            ret = app_install_local("6EB0217704000486", apk_path, launch=True)
            logger.info("Ret: %s", ret)
        return

    # start local server
    provider_url = "http://" + current_ip() + ":" + str(args.port)
    app = make_app()
    app.listen(args.port)
    logger.info("ProviderURL: %s", provider_url)

    fetching.get_all()

    # connect to atxserver2
    global hbconn
    hbconn = await heartbeat_connect(args.server,
                                     secret=secret,
                                     self_url=provider_url,
                                     owner=owner_email)

    await device_watch(args.allow_remote)


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
    # if os.path.getsize(os.path.join(__curdir__,
    #                                 "vendor/app-uiautomator.apk")) < 1000:
    #     sys.exit("Did you forget run\n\tgit lfs install\n\tgit lfs pull")

    try:
        IOLoop.current().run_sync(async_main)
    except KeyboardInterrupt:
        logger.info("Interrupt catched")
