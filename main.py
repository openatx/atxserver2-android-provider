#!/usr/bin/env python3
# coding: utf-8
#

import subprocess
from logzero import logger


def main():
    logger.info("tcpproxy.js start")
    p1 = subprocess.Popen(['node', 'tcpproxy.js', '8100', 'localhost', '8000'])
    logger.info("tcpproxy.js end")

    logger.info("adbkit start")
    p2 = subprocess.Popen(['node', 'node_modules/.bin/adbkit', '-h'])
    logger.info("adbkit end")

    p1.wait()
    p2.wait()

if __name__ == '__main__':
    main()
