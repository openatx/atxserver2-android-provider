# coding: utf-8
#
# Refs adb SERVICES.TXT
# https://github.com/aosp-mirror/platform_system_core/blob/master/adb/SERVICES.TXT

import os
import subprocess
from collections import namedtuple

import tornado.iostream
from logzero import logger
from tornado import gen
from tornado.tcpclient import TCPClient


OKAY = "OKAY"
FAIL = "FAIL"


DeviceItem = namedtuple("Device", ['serial', 'status'])
DeviceEvent = namedtuple('DeviceEvent', ['present', 'serial', 'status'])
ForwardItem = namedtuple("ForwardItem", ['serial', 'local', 'remote'])


class AdbError(Exception):
    """ adb error """


class AdbStreamConnection(tornado.iostream.IOStream):
    """
    Example usgae:
        async with AdbStreamConnection(host, port) as c:
            c.send_cmd("host:kill")
    """

    def __init__(self, host, port):
        self.__host = host
        self.__port = port
        self.__stream = None

    @property
    def stream(self):
        return self.__stream

    async def send_cmd(self, cmd: str):
        await self.stream.write("{:04x}{}".format(len(cmd),
                                                  cmd).encode('utf-8'))

    async def read_bytes(self, num: int):
        return (await self.stream.read_bytes(num)).decode()

    async def read_string(self):
        lenstr = await self.read_bytes(4)
        msgsize = int(lenstr, 16)
        return await self.read_bytes(msgsize)

    async def check_okay(self):
        data = await self.read_bytes(4)
        if data == FAIL:
            raise AdbError(await self.read_string())
        elif data == OKAY:
            return
        else:
            raise AdbError("Unknown data: %s" % data)

    async def connect(self):
        adb_host = self.__host or os.environ.get(
            "ANDROID_ADB_SERVER_HOST", "127.0.0.1")
        adb_port = self.__port or int(os.environ.get(
            "ANDROID_ADB_SERVER_PORT", 5037))
        stream = await TCPClient().connect(adb_host, adb_port)
        self.__stream = stream
        return self

    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, exc_type, exc, tb):
        self.stream.close()


class AdbClient(object):
    def __init__(self):
        self._stream = None

    def connect(self, host=None, port=None) -> AdbStreamConnection:
        return AdbStreamConnection(host, port)

    async def server_version(self) -> int:
        async with self.connect() as c:
            await c.send_cmd("host:version")
            await c.check_okay()
            return int(await c.read_string(), 16)

    async def track_devices(self):
        """
        yield DeviceEvent according to track-devices

        Example:
            async for event in track_devices():
                print(event)
                # output: DeviceEvent(present=True, serial='xxxx', status='device')
        """
        orig_devices = []
        while True:
            try:
                async for content in self._unsafe_track_devices():
                    curr_devices = self.output2devices(
                        content, limit_status=['device'])
                    for evt in self._diff_devices(orig_devices, curr_devices):
                        yield evt
                    orig_devices = curr_devices
            except tornado.iostream.StreamClosedError:
                # adb server maybe killed
                for evt in self._diff_devices(orig_devices, []):
                    yield evt
                orig_devices = []

                sleep = 1.0
                logger.info(
                    "adb connection is down, retry after %.1fs" % sleep)
                await gen.sleep(sleep)
                subprocess.run(['adb', 'start-server'])
                version = await self.server_version()
                logger.info("adb-server started, version: %d", version)

    async def _unsafe_track_devices(self):
        async with self.connect() as conn:
            await conn.send_cmd("host:track-devices")
            await conn.check_okay()
            while True:
                yield await conn.read_string()

    def _diff_devices(self, orig_devices: list, curr_devices: list):
        """ Return iter(DeviceEvent) """
        for d in set(orig_devices).difference(curr_devices):
            yield DeviceEvent(False, d.serial, d.status)
        for d in set(curr_devices).difference(orig_devices):
            yield DeviceEvent(True, d.serial, d.status)

    def output2devices(self, output: str, limit_status=[]):
        """
        Args:
            outptu: str of adb devices output

        Returns:
            list of DeviceItem
        """
        results = []
        for line in output.splitlines():
            fields = line.strip().split("\t", maxsplit=1)
            if len(fields) != 2:
                continue
            serial, status = fields[0], fields[1]

            if limit_status:
                if status in limit_status:
                    results.append(DeviceItem(serial, status))
            else:
                results.append(DeviceItem(serial, status))
        return results

    async def shell(self, serial: str, command: str):
        async with self.connect() as conn:
            await conn.send_cmd("host:transport:"+serial)
            await conn.check_okay()
            await conn.send_cmd("shell:"+command)
            await conn.check_okay()
            output = await conn.stream.read_until_close()
            return output.decode('utf-8')

    async def forward_list(self):
        async with self.connect() as conn:
            # adb 1.0.40 not support host-local
            await conn.send_cmd("host:list-forward")
            await conn.check_okay()
            content = await conn.read_string()
            for line in content.splitlines():
                parts = line.split()
                if len(parts) != 3:
                    continue
                yield ForwardItem(*parts)

    async def forward_remove(self, local=None):
        async with self.connect() as conn:
            if local:
                await conn.send_cmd("host:killforward:"+local)
            else:
                await conn.send_cmd("host:killforward-all")
            await conn.check_okay()

    async def forward(self, serial: str, local: str, remote: str, norebind=False):
        """
        Args:
            serial: device serial
            local, remote (str): tcp:<port> | localabstract:<name>
            norebind(bool): set to true will fail it when 
                    there is already a forward connection from <local>
        """
        async with self.connect() as conn:
            cmds = ["host-serial", serial, "forward"]
            if norebind:
                cmds.append('norebind')
            cmds.append(local+";"+remote)
            await conn.send_cmd(":".join(cmds))
            await conn.check_okay()

    async def devices(self):
        """
        Return:
            list of devices
        """
        async with self.connect() as conn:
            await conn.send_cmd("host:devices")
            await conn.check_okay()
            content = await conn.read_string()
            return self.output2devices(content)


adb = AdbClient()
