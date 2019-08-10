#!/usr/bin/env python
# coding: utf-8
#

import shutil
import tarfile
import tempfile
import zipfile

import humanize
import progress.bar
import requests

from logzero import logger


class DownloadBar(progress.bar.Bar):
    message = "Downloading"
    suffix = '%(current_size)s / %(total_size)s'

    @property
    def total_size(self):
        return humanize.naturalsize(self.max, gnu=True)

    @property
    def current_size(self):
        return humanize.naturalsize(self.index, gnu=True)


def mirror_download(url: str, target: str):
    github_host = "https://github.com"
    if url.startswith(github_host):
        mirror_url = "http://tool.appetizer.io" + url[len(
            github_host):]  # mirror of github
        try:
            return download(mirror_url, target)
        except requests.RequestException as e:
            logger.debug("download from mirror error, use origin source")

    return download(url, target)


def download(url: str, storepath: str):
    r = requests.get(url, stream=True)
    r.raise_for_status()
    file_size = int(r.headers.get("Content-Length"))

    bar = DownloadBar(storepath, max=file_size)
    chunk_length = 16 * 1024
    with open(storepath + '.part', 'wb') as f:
        for buf in r.iter_content(chunk_length):
            f.write(buf)
            bar.next(len(buf))
        bar.finish()
    shutil.move(storepath + '.part', storepath)


def get_binary_url(version: str, arch: str) -> str:
    """
    get atx-agent url
    """
    return "https://github.com/openatx/atx-agent/releases/download/{0}/atx-agent_{0}_linux_{1}.tar.gz".format(
            version, arch)


def create_bundle(version: str):
    print(">>> Download atx-agent verison:", version)
    with tempfile.TemporaryDirectory(prefix="tmp-") as tmpdir:
        target_zip = f"atx-agent-{version}.zip"
        tmp_target_zip = target_zip + ".part"

        with zipfile.ZipFile(tmp_target_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(version, "")

            for arch in ("386", "amd64", "armv6", "armv7"):
                storepath = tmpdir + "/atx-agent-%s.tar.gz" % arch
                url = get_binary_url(version, arch)
                mirror_download(url, storepath)

                with tarfile.open(storepath, "r:gz") as t:
                    t.extract("atx-agent", path=tmpdir+"/"+arch)
                    z.write(
                        "/".join([tmpdir, arch, "atx-agent"]), "atx-agent-"+arch)
        shutil.move(tmp_target_zip, target_zip)
        print(">>> Zip created", target_zip)


if __name__ == "__main__":
    from uiautomator2.version import __atx_agent_version__
    create_bundle(__atx_agent_version__)
