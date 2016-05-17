#!/usr/bin/python2

# Copyright (C) 2016 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
Script to install/upgrade the openvstorage-sdm package
"""

import sys
from datetime import datetime
sys.path.append('/opt/asd-manager')


def _log(message):
    print '{0} - {1}'.format(str(datetime.now()), message)

if __name__ == '__main__':
    from source.tools.filemutex import file_mutex
    from subprocess import check_output

    _log('Upgrading package openvstorage-sdm')
    with file_mutex('package_update'):
        _log('Lock in place, starting upgrade')
        for line in check_output('apt-get install -y --force-yes openvstorage-sdm', shell=True).splitlines():
            _log('  {0}'.format(line))
    _log('Upgrade completed')
