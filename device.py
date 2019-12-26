# coding: utf-8
#

import os
import subprocess
import traceback
import zipfile

from adbutils import adb as adbclient
from logzero import logger

import apkutils2 as apkutils
from asyncadb import adb
from device_names import device_names
from core.freeport import freeport
from core.utils import current_ip
from core import fetching

STATUS_INIT = "init"
STATUS_OKAY = "ready"
STATUS_FAIL = "fail"


class InitError(Exception):
    """ device init error """


async def nop_callback(*args, **kwargs):
    pass


class AndroidDevice(object):
    def __init__(self, serial: str, callback=nop_callback):
        self._serial = serial
        self._procs = []
        self._current_ip = current_ip()
        self._device = adbclient.device(serial)
        self._callback = callback

    def __repr__(self):
        return "[" + self._serial + "]"

    @property
    def serial(self):
        return self._serial

    async def run_forever(self):
        try:
            await self.init()
        except Exception as e:
            logger.warning("Init failed: %s", e)

    async def init(self):
        """
        do forward and start proxy
        """
        logger.info("Init device: %s", self._serial)
        self._callback(STATUS_INIT)

        self._init_binaries()
        self._init_apks()
        await self._init_forwards()

        await adb.shell(self._serial,
                        "/data/local/tmp/atx-agent server --stop")
        await adb.shell(self._serial,
                        "/data/local/tmp/atx-agent server --nouia -d")

    async def open_identify(self):
        await adb.shell(
            self._serial,
            "am start -n com.github.uiautomator/.IdentifyActivity -e theme black"
        )

    def _init_binaries(self):
        # minitouch, minicap, minicap.so
        d = self._device
        sdk = d.getprop("ro.build.version.sdk")  # eg 26
        abi = d.getprop('ro.product.cpu.abi')  # eg arm64-v8a
        abis = (d.getprop('ro.product.cpu.abilist').strip() or abi).split(",")
        # pre = d.getprop('ro.build.version.preview_sdk')  # eg 0
        # if pre and pre != "0":
        #    sdk = sdk + pre

        logger.debug("%s sdk: %s, abi: %s, abis: %s", self, sdk, abi, abis)

        stf_zippath = fetching.get_stf_binaries()
        zip_folder, _ = os.path.splitext(os.path.basename(stf_zippath))
        prefix = zip_folder + "/node_modules/minicap-prebuilt/prebuilt/"
        self._push_stf(prefix + abi + "/lib/android-" + sdk + "/minicap.so",
                       "/data/local/tmp/minicap.so",
                       mode=0o644,
                       zipfile_path=stf_zippath)
        self._push_stf(prefix + abi + "/bin/minicap",
                       "/data/local/tmp/minicap",
                       zipfile_path=stf_zippath)

        prefix = zip_folder + "/node_modules/minitouch-prebuilt/prebuilt/"
        self._push_stf(prefix + abi + "/bin/minitouch",
                       "/data/local/tmp/minitouch",
                       zipfile_path=stf_zippath)

        # atx-agent
        abimaps = {
            'armeabi-v7a': 'atx-agent-armv7',
            'arm64-v8a': 'atx-agent-armv7',
            'armeabi': 'atx-agent-armv6',
            'x86': 'atx-agent-386',
        }
        okfiles = [abimaps[abi] for abi in abis if abi in abimaps]
        if not okfiles:
            raise InitError("no avaliable abilist", abis)
        logger.debug("%s use atx-agent: %s", self, okfiles[0])
        zipfile_path = fetching.get_atx_agent_bundle()
        self._push_stf(okfiles[0],
                       "/data/local/tmp/atx-agent",
                       zipfile_path=zipfile_path)

    def _push_stf(self,
                  path: str,
                  dest: str,
                  zipfile_path: str,
                  mode=0o755):
        """ push minicap and minitouch from zip """
        with zipfile.ZipFile(zipfile_path) as z:
            if path not in z.namelist():
                logger.warning("stf stuff %s not found", path)
                return
            src_info = z.getinfo(path)
            dest_info = self._device.sync.stat(dest)
            if dest_info.size == src_info.file_size and dest_info.mode & mode == mode:
                logger.debug("%s already pushed %s", self, path)
                return
            with z.open(path) as f:
                self._device.sync.push(f, dest, mode)

    def _init_apks(self):
        whatsinput_apk_path = fetching.get_whatsinput_apk()
        self._install_apk(whatsinput_apk_path)
        for apk_path in fetching.get_uiautomator_apks():
            print("APKPath:", apk_path)
            self._install_apk(apk_path)

    def _install_apk(self, path: str):
        assert path, "Invalid %s" % path
        try:
            m = apkutils.APK(path).manifest
            info = self._device.package_info(m.package_name)
            if info and m.version_code == info[
                    'version_code'] and m.version_name == info['version_name']:
                logger.debug("%s already installed %s", self, path)
            else:
                print(info, ":", m.version_code, m.version_name)
                logger.debug("%s install %s", self, path)
                self._device.install(path, force=True)
        except Exception as e:
            traceback.print_exc()
            logger.warning("%s Install apk %s error %s", self, path, e)

    async def _init_forwards(self):
        logger.debug("%s forward atx-agent", self)
        self._atx_proxy_port = await self.proxy_device_port(7912)
        self._whatsinput_port = await self.proxy_device_port(6677)

        port = self._adb_remote_port = freeport.get()
        logger.debug("%s adbkit start, port %d", self, port)

        self.run_background([
            'node', 'node_modules/adbkit/bin/adbkit', 'usb-device-to-tcp',
            '-p',
            str(self._adb_remote_port), self._serial
        ],
                            silent=True)

    def addrs(self):
        def port2addr(port):
            return self._current_ip + ":" + str(port)

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
        local_port = await self.adb_forward_to_any("tcp:" + str(device_port))
        listen_port = freeport.get()
        logger.debug("%s tcpproxy.js start *:%d -> %d", self, listen_port,
                     local_port)
        self.run_background([
            'node', 'tcpproxy.js',
            str(listen_port), 'localhost',
            str(local_port)
        ],
                            silent=True)
        return listen_port

    def run_background(self, *args, **kwargs):
        silent = kwargs.pop('silent', False)
        if silent:
            kwargs['stdout'] = subprocess.DEVNULL
            kwargs['stderr'] = subprocess.DEVNULL
        p = subprocess.Popen(*args, **kwargs)
        self._procs.append(p)
        return p

    async def getprop(self, name: str) -> str:
        value = await adb.shell(self._serial, "getprop " + name)
        return value.strip()

    async def properties(self):
        brand = await self.getprop("ro.product.brand")
        model = await self.getprop("ro.product.model")
        version = await self.getprop("ro.build.version.release")

        return {
            "serial": self._serial,
            "brand": brand,
            "version": version,
            "model": model,
            "name": device_names.get(model, model),
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
