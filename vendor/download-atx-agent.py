#!/usr/bin/env python
# coding: utf-8
#

from uiautomator2.version import __atx_agent_version__

import humanize
import zipfile
import tarfile
import requests
import progress.bar
import shutil
import tempfile


class DownloadBar(progress.bar.Bar):
    message = "Downloading"
    suffix = '%(current_size)s / %(total_size)s'

    @property
    def total_size(self):
        return humanize.naturalsize(self.max, gnu=True)

    @property
    def current_size(self):
        return humanize.naturalsize(self.index, gnu=True)


def download(arch: str, storepath: str):
    r = requests.get(
        "https://github.com/openatx/atx-agent/releases/download/{0}/atx-agent_{0}_linux_{1}.tar.gz".format(
            __atx_agent_version__, arch), stream=True)
    r.raise_for_status()
    file_size = int(r.headers.get("Content-Length"))

    bar = DownloadBar(storepath, max=file_size)
    with open(storepath + '.tmp', 'wb') as f:
        chunk_length = 16 * 1024
        while 1:
            buf = r.raw.read(chunk_length)
            if not buf:
                break
            f.write(buf)
            bar.next(len(buf))
        bar.finish()
    shutil.move(storepath + '.tmp', storepath)


def main():
    print(">>> Download atx-agent verison:", __atx_agent_version__)
    with tempfile.TemporaryDirectory(prefix="tmp-") as tmpdir:
        target_zip = "atx-agent-latest.zip"

        with zipfile.ZipFile(target_zip + ".tmp", "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(__atx_agent_version__, "")

            for arch in ("386", "amd64", "armv6", "armv7"):
                storepath = tmpdir + "/atx-agent-%s.tar.gz" % arch
                download(arch, storepath)

                with tarfile.open(storepath, "r:gz") as t:
                    t.extract("atx-agent", path=tmpdir+"/"+arch)
                    z.write(
                        "/".join([tmpdir, arch, "atx-agent"]), "atx-agent-"+arch)
        shutil.move(target_zip+".tmp", target_zip)
        print(">>> Zip created", target_zip)


if __name__ == "__main__":
    main()
