# coding: utf-8
#

import progress.bar
import requests
from uiautomator2.version import __apk_version__


def download(url, target):
    print("Download", target)
    r = requests.get(url, stream=True)
    r.raise_for_status()

    bar = progress.bar.Bar()
    bar.max = int(r.headers.get("content-length"))
    with open(target, "wb") as f:
        for chunk in r.iter_content(chunk_size=4096):
            f.write(chunk)
            bar.next(len(chunk))
        bar.finish()


def main():
    url_apk = "https://github.com/openatx/android-uiautomator-server/releases/download/{}/app-uiautomator.apk".format(
        __apk_version__)
    url_test_apk = "https://github.com/openatx/android-uiautomator-server/releases/download/{}/app-uiautomator-test.apk".format(
        __apk_version__)
    download(url_apk, "app-uiautomator.apk")
    download(url_test_apk, "app-uiautomator-test.apk")


if __name__ == "__main__":
    main()
