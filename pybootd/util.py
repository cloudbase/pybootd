# -*- coding: utf-8 -*-
#
# Copyright (c) 2010-2016 Emmanuel Blot <emmanuel.blot@free.fr>
# Copyright (c) 2010-2011 Neotion
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from array import array
import logging
import re
import socket
import struct
import subprocess
import sys

from six.moves.configparser import SafeConfigParser
from six import PY3, integer_types, binary_type

try:
    import netifaces
except ImportError:
    import os
    if os.uname()[0].lower() == 'darwin':
        raise ImportError('netifaces package is not installed')
    netifaces = None

# String values evaluated as true boolean values
TRUE_BOOLEANS = ['on', 'high', 'true', 'enable', 'enabled', 'yes',  '1']
# String values evaluated as false boolean values
FALSE_BOOLEANS = ['off', 'low', 'false', 'disable', 'disabled', 'no', '0']
# ASCII or '.' filter
ASCIIFILTER = bytearray((''.join([(
    (len(repr(chr(_x))) == 3) or (_x == 0x5c)) and chr(_x) or '.'
    for _x in range(128)]) + '.' * 128).encode('ascii'))


def to_int(value):
    """Parse a value and convert it into an integer value if possible.

       Input value may be:
       - a string with an integer coded as a decimal value
       - a string with an integer coded as a hexadecimal value
       - a integral value
       - a integral value with a unit specifier (kilo or mega)
    """
    if not value:
        return 0
    if isinstance(value, integer_types):
        return int(value)
    mo = re.match('^\s*(\d+)\s*(?:([KMkm]i?)?B?)?\s*$', value)
    if mo:
        mult = {'K': (1000),
                'KI': (1 << 10),
                'M': (1000 * 1000),
                'MI': (1 << 20)}
        value = int(mo.group(1))
        if mo.group(2):
            value *= mult[mo.group(2).upper()]
        return value
    return int(value.strip(), value.startswith('0x') and 16 or 10)


def to_bool(value, permissive=True, allow_int=False):
    """Parse a string and convert it into a boolean value if possible.

       :param value: the value to parse and convert
       :param permissive: default to the False value if parsing fails
       :param allow_int: allow an integral type as the input value

       Input value may be:
       - a string with an integer value, if `allow_int` is enabled
       - a boolean value
       - a string with a common boolean definition
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if allow_int:
            return bool(value)
        else:
            if permissive:
                return False
            raise ValueError("Invalid boolean value: '%d'", value)
    if value.lower() in TRUE_BOOLEANS:
        return True
    if permissive or (value.lower() in FALSE_BOOLEANS):
        return False
    raise ValueError('"Invalid boolean value: "%s"' % value)


def hexline(data, sep=' '):
    """Convert a binary buffer into a hexadecimal representation

       Return a string with hexadecimal values and ASCII representation
       of the buffer data
    """
    try:
        if isinstance(data, (binary_type, array)):
            src = bytearray(data)
        elif isinstance(data, bytearray):
            src = data
        elif isinstance(data, str):
            src = data.encode()
        else:
            # data may be a list/tuple
            src = bytearray(b''.join(data))
    except Exception:
        raise TypeError("Unsupported data type '%s'" % type(data))

    hexa = sep.join(["%02x" % x for x in src])
    printable = src.translate(ASCIIFILTER).decode('ascii')
    return "(%d) %s : %s" % (len(data), hexa, printable)


def logger_factory(logtype='syslog', logfile=None, level='WARNING',
                   logid='PXEd', format=None):
    # this code has been copied from Trac (MIT modified license)
    logger = logging.getLogger(logid)
    logtype = logtype.lower()
    if logtype == 'file':
        hdlr = logging.FileHandler(logfile)
    elif logtype in ('winlog', 'eventlog', 'nteventlog'):
        # Requires win32 extensions
        hdlr = logging.handlers.NTEventLogHandler(logid,
                                                  logtype='Application')
    elif logtype in ('syslog', 'unix'):
        hdlr = logging.handlers.SysLogHandler('/dev/log')
    elif logtype in ('stderr'):
        hdlr = logging.StreamHandler(sys.stderr)
    else:
        hdlr = logging.handlers.BufferingHandler(0)

    if not format:
        format = 'PXEd[%(module)s] %(levelname)s: %(message)s'
        if logtype in ('file', 'stderr'):
            format = '%(asctime)s ' + format
    datefmt = ''
    if logtype == 'stderr':
        datefmt = '%X'
    level = level.upper()
    if level in ('DEBUG', 'ALL'):
        logger.setLevel(logging.DEBUG)
    elif level == 'INFO':
        logger.setLevel(logging.INFO)
    elif level == 'ERROR':
        logger.setLevel(logging.ERROR)
    elif level == 'CRITICAL':
        logger.setLevel(logging.CRITICAL)
    else:
        logger.setLevel(logging.WARNING)
    formatter = logging.Formatter(format, datefmt)
    hdlr.setFormatter(formatter)
    logger.addHandler(hdlr)

    def logerror(record):
        import traceback
        print_(record.msg)
        print_(record.args)
        traceback.print_exc()
    # uncomment the following line to show logger formatting error
    #hdlr.handleError = logerror

    return logger


def iptoint(ipstr):
    return struct.unpack('!I', socket.inet_aton(ipstr))[0]


def inttoip(ipval):
    return socket.inet_ntoa(struct.pack('!I', ipval))


def _netifaces_get_iface_config(address):
    pool = iptoint(address)
    for iface in netifaces.interfaces():
        ifinfo = netifaces.ifaddresses(iface)
        if netifaces.AF_INET not in ifinfo:
            continue
        for inetinfo in netifaces.ifaddresses(iface)[netifaces.AF_INET]:
            addr_s = inetinfo.get('addr')
            netmask_s = inetinfo.get('netmask')
            if addr_s is None or netmask_s is None:
                continue

            addr = iptoint(addr_s)
            mask = iptoint(netmask_s)
            ip = addr & mask
            ip_client = pool & mask
            delta = ip ^ ip_client
            if not delta:
                config = {'ifname': iface,
                          'server': inttoip(addr),
                          'net': inttoip(ip),
                          'mask': inttoip(mask)}
                return config
    return None


def _iproute_get_iface_config(address):
    pool = iptoint(address)
    iplines = []
    iplines = (line.strip()
               for line in subprocess.check_output(
               "ip address show".split(" ")).rstrip("\n").split('\n'))
    iface = None
    for l in iplines:
        items = l.split()
        if not items:
            continue
        if items[0].endswith(':'):
            iface = items[1][:-1]
        elif items[0] == 'inet':
            saddr, smasklen = items[1].split('/', 1)
            addr = iptoint(saddr)
            masklen = int(smasklen)
            mask = ((1 << masklen) - 1) << (32 - masklen)
            ip = addr & mask
            ip_client = pool & mask
            delta = ip ^ ip_client
            if not delta:
                return {'ifname': iface,
                        'server': inttoip(addr),
                        'net': inttoip(ip),
                        'mask': inttoip(mask)}
    return None


def get_iface_config(address):
    if not address:
        return None
    if not netifaces:
        return _iproute_get_iface_config(address)
    return _netifaces_get_iface_config(address)


class EasyConfigParser(SafeConfigParser):
    "ConfigParser extension to support default config values"

    def get_opt(self, section, option, default=None):
        if not self.has_section(section):
            return default
        if not self.has_option(section, option):
            return default
        return SafeConfigParser.get(self, section, option)
