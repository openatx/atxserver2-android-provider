# coding: utf-8
#
# Refs adb SERVICES.TXT
# https://github.com/aosp-mirror/platform_system_core/blob/master/adb/SERVICES.TXT

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


class AdbError(Exception):
    """ adb error """


class Adb(object):
    def __init__(self):
        self._stream = None

    async def connect(self):
        return await TCPClient().connect("127.0.0.1", 5037)

    async def server_version(self) -> int:
        stream = await self.connect()
        await self.send_cmd("host:version", stream)
        await self._check_okay(stream)
        return int(await self.read_string(stream), 16)

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
        stream = await self.connect()
        await self.send_cmd("host:track-devices", stream)
        await self._check_okay(stream)
        while True:
            yield await self.read_string(stream)

    def _diff_devices(self, orig_devices: list, curr_devices: list):
        """ Return iter(DeviceEvent) """
        for d in set(orig_devices).difference(curr_devices):
            yield DeviceEvent(False, d.serial, d.status)
        for d in set(curr_devices).difference(orig_devices):
            yield DeviceEvent(True, d.serial, d.status)

    async def _check_okay(self, stream):
        data = await self.read_bytes(4, stream)
        if data == FAIL:
            raise AdbError(await self.read_string(stream))
        elif data == OKAY:
            return
        else:
            raise AdbError("Unknown data: %s" % data)

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
        stream = await self.connect()
        await self.send_cmd("host:transport:"+serial, stream)
        await self._check_okay(stream)
        await self.send_cmd("shell:"+command, stream)
        await self._check_okay(stream)
        output = await stream.read_until_close()
        return output.decode('utf-8')

    async def devices(self):
        """
        Return:
            list of devices
        """
        stream = await self.connect()
        await self.send_cmd("host:devices", stream)
        await self._check_okay(stream)
        content = await self.read_string(stream)
        return self.output2devices(content)

    async def send_cmd(self, cmd: str, stream=None):
        stream = stream or self._stream
        await stream.write("{:04x}{}".format(len(cmd),
                                             cmd).encode('utf-8'))

    async def read_bytes(self, num_bytes: int, stream=None):
        stream = stream or self._stream
        return (await stream.read_bytes(num_bytes)).decode()

    async def read_string(self, stream=None):
        stream = stream or self._stream
        lenstr = await self.read_bytes(4, stream)
        msgsize = int(lenstr, 16)
        return await self.read_bytes(msgsize, stream)
