# coding: utf-8
#

import collections
import random
import re
import socket
import string
import netifaces

def current_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def current_ip_network():
    def calc_network(netmask):
        result = ""
        for num in netmask.split('.'):
            temp = str(bin(int(num)))[2:]
            result += temp
        return str(len([n for n in result if n != '0']))

    machine_nick_name = netifaces.gateways()['default'][netifaces.AF_INET][1]
    match_info = [netifaces.ifaddresses(interface)[netifaces.AF_INET] for interface in netifaces.interfaces() if interface == machine_nick_name]
    ip = current_ip()
    ip_and_network = ip + '/' + 'unknow'
    # normally, if will match
    if match_info:
        try:
            # addr = match_info[0][0]['addr']
            netmask = match_info[0][0]['netmask']
            net = calc_network(netmask)
            ip_and_network = ip + '/' + net
        except Exception as e:
            pass
    return ip_and_network

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
