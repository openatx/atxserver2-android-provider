# coding: utf-8
#
from collections import namedtuple
from tornado.tcpclient import TCPClient


OKAY = "OKAY"
FAIL = "FAIL"


DeviceItem = namedtuple("Device", ['serial', 'status'])

class ADB(object):
    def __init__(self):
        self._stream = None

    async def devices(self):
        """
        Return:
            list of devices
        """
        
        self._stream = await TCPClient().connect('127.0.0.1', 5037)
        await self.send_cmd("host:devices")
        data = await self.read_bytes(4)
        if data == OKAY:
            length = int(await self.read_bytes(4), 16)
            content = await self.read_bytes(length)
            devices = []
            for line in content.splitlines():
                fields = line.strip().split("\t", maxsplit=1)
                if len(fields) != 2:
                    continue
                serial, status = fields[0], fields[1]
                devices.append(DeviceItem(serial, status))
            return devices
        elif data == FAIL:
            length = int(await self.read_bytes(4), 16)
            print("Len:", length)
            message = await self.read_bytes(length)
            print("Message:", message)
        else:
            print("Unknown head:", data)

    async def send_cmd(self, cmd: str):
        await self._stream.write("{:04x}{}".format(len(cmd),
                                                   cmd).encode('utf-8'))

    async def read_bytes(self, num_bytes: int):
        return (await self._stream.read_bytes(num_bytes)).decode()