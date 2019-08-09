# coding: utf-8
import os
import shutil
import tarfile
import tempfile
import zipfile

import humanize
import requests
from logzero import logger
from uiautomator2.version import __atx_agent_version__

__all__ = ["get_atx_agent_bundle"]


def get_atx_agent_bundle() -> str:
    """
    bundle all platform atx-agent binary into one zip file
    """
    version = __atx_agent_version__
    target_zip = f"vendor/atx-agent-{version}.zip"
    if not os.path.isfile(target_zip):
        os.makedirs("vendor", exist_ok=True)
        create_atx_agent_bundle(version, target_zip)
    return target_zip


def create_atx_agent_bundle(version: str, target_zip: str):
    print(">>> Bundle atx-agent verison:", version)
    if not target_zip:
        target_zip = f"atx-agent-{version}.zip"

    def binary_url(version: str, arch: str) -> str:
        return "https://github.com/openatx/atx-agent/releases/download/{0}/atx-agent_{0}_linux_{1}.tar.gz".format(
            version, arch)

    with tempfile.TemporaryDirectory(prefix="tmp-") as tmpdir:
        tmp_target_zip = target_zip + ".part"

        with zipfile.ZipFile(tmp_target_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(version, "")

            for arch in ("386", "amd64", "armv6", "armv7"):
                storepath = tmpdir + "/atx-agent-%s.tar.gz" % arch
                url = binary_url(version, arch)
                mirror_download(url, storepath)

                with tarfile.open(storepath, "r:gz") as t:
                    t.extract("atx-agent", path=tmpdir+"/"+arch)
                    z.write(
                        "/".join([tmpdir, arch, "atx-agent"]), "atx-agent-"+arch)
        shutil.move(tmp_target_zip, target_zip)
        print(">>> Zip created", target_zip)


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
    total_size = int(r.headers.get("Content-Length"))
    bytes_so_far = 0
    prefix = "Downloading %s" % os.path.basename(url)
    chunk_length = 16 * 1024
    with open(storepath + '.part', 'wb') as f:
        for buf in r.iter_content(chunk_length):
            bytes_so_far += len(buf)
            print(f"\r{prefix} {bytes_so_far} / {total_size}",
                  end="", flush=True)
            f.write(buf)
        print(" [Done]")
    shutil.move(storepath + '.part', storepath)


if __name__ == "__main__":
    bundle_path = get_atx_agent_bundle()
    print("Bundle:", bundle_path)
