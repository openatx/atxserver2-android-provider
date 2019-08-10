# coding: utf-8
#

import collections
import random
import re
import socket
import string


def current_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def update_recursive(d: dict, u: dict) -> dict:
    for k, v in u.items():
        if isinstance(v, collections.Mapping):
            # d.get(k) may return None
            d[k] = update_recursive(d.get(k) or {}, v)
        else:
            d[k] = v
    return d


def fix_url(url, scheme=None):
    if not re.match(r"^(http|ws)s?://", url):
        url = "http://"+url
    if scheme:
        url = re.compile(r"^http").sub(scheme, url)
    return url


def id_generator(length=10):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
