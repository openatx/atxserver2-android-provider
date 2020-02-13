# coding: utf-8
import os
import shutil
import tarfile
import tempfile
import zipfile

import humanize
import requests
from logzero import logger
from uiautomator2.version import __apk_version__, __atx_agent_version__

import settings

__all__ = [
    "get_atx_agent_bundle", "get_uiautomator_apks", "get_whatsinput_apk"
]


def get_atx_agent_bundle() -> str:
    """
    bundle all platform atx-agent binary into one zip file
    """
    version = settings.atx_agent_version
    target_zip = f"vendor/atx-agent-{version}.zip"
    if not os.path.isfile(target_zip):
        os.makedirs("vendor", exist_ok=True)
        create_atx_agent_bundle(version, target_zip)
    return target_zip


def get_uiautomator_apks() -> tuple:
    version = __apk_version__
    print(">>> app-uiautomator.apk verison:", version)
    apk_url = f"https://github.com/openatx/android-uiautomator-server/releases/download/{version}/app-uiautomator.apk"
    target_dir = f"vendor/app-uiautomator-{version}"
    apk_path = mirror_download(apk_url,
                               os.path.join(target_dir, "app-uiautomator.apk"))

    apk_test_url = f"https://github.com/openatx/android-uiautomator-server/releases/download/{version}/app-uiautomator-test.apk"
    print(">>> app-uiautomator-test.apk verison:", version)
    apk_test_path = mirror_download(
        apk_test_url, os.path.join(target_dir, "app-uiautomator-test.apk"))
    return (apk_path, apk_test_path)


def get_whatsinput_apk() -> str:
    target_path = "vendor/WhatsInput-1.0.apk"
    mirror_download(
        "https://github.com/openatx/atxserver2-android-provider/releases/download/v0.2.0/WhatsInput_v1.0.apk",
        target_path)
    return target_path


def get_stf_binaries() -> str:
    """
    Download from https://github.com/openatx/stf-binaries

    Tag 0.2, support to Android P
    """
    version = "0.2.1"
    target_path = f"vendor/stf-binaries-{version}.zip"
    mirror_download(
        f"https://github.com/openatx/stf-binaries/archive/{version}.zip",
        target_path)
    return target_path


def get_all():
    get_atx_agent_bundle()
    get_uiautomator_apks()
    get_whatsinput_apk()
    get_stf_binaries()


def create_atx_agent_bundle(version: str, target_zip: str):
    print(">>> Bundle atx-agent verison:", version)
    if not target_zip:
        target_zip = f"atx-agent-{version}.zip"

    def binary_url(version: str, arch: str) -> str:
        return "https://github.com/openatx/atx-agent/releases/download/{0}/atx-agent_{0}_linux_{1}.tar.gz".format(
            version, arch)

    with tempfile.TemporaryDirectory(prefix="tmp-") as tmpdir:
        tmp_target_zip = target_zip + ".part"

        with zipfile.ZipFile(tmp_target_zip,
                             "w",
                             compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(version, "")

            for arch in ("386", "amd64", "armv6", "armv7"):
                storepath = tmpdir + "/atx-agent-%s.tar.gz" % arch
                url = binary_url(version, arch)
                mirror_download(url, storepath)

                with tarfile.open(storepath, "r:gz") as t:
                    t.extract("atx-agent", path=tmpdir + "/" + arch)
                    z.write("/".join([tmpdir, arch, "atx-agent"]),
                            "atx-agent-" + arch)
        shutil.move(tmp_target_zip, target_zip)
        print(">>> Zip created", target_zip)


def mirror_download(url: str, target: str) -> str:
    """
    Returns:
        target path
    """
    if os.path.exists(target):
        return target
    github_host = "https://github.com"
    if url.startswith(github_host):
        mirror_url = "http://tool.appetizer.io" + url[len(
            github_host):]  # mirror of github
        try:
            return download(mirror_url, target)
        except (requests.RequestException, ValueError) as e:
            logger.debug("download from mirror error, use origin source")

    return download(url, target)


def download(url: str, storepath: str):
    target_dir = os.path.dirname(storepath) or "."
    os.makedirs(target_dir, exist_ok=True)

    r = requests.get(url, stream=True)
    r.raise_for_status()
    total_size = int(r.headers.get("Content-Length", "-1"))
    bytes_so_far = 0
    prefix = "Downloading %s" % os.path.basename(storepath)
    chunk_length = 16 * 1024
    with open(storepath + '.part', 'wb') as f:
        for buf in r.iter_content(chunk_length):
            bytes_so_far += len(buf)
            print(f"\r{prefix} {bytes_so_far} / {total_size}",
                  end="",
                  flush=True)
            f.write(buf)
        print(" [Done]")
    if total_size != -1 and os.path.getsize(storepath + ".part") != total_size:
        raise ValueError("download size mismatch")
    shutil.move(storepath + '.part', storepath)


if __name__ == "__main__":
    bundle_path = get_atx_agent_bundle()
    print("Bundle:", bundle_path)
