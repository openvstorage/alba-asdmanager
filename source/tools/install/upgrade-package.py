#!/usr/bin/python2

# Copyright 2015 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Script to install/upgrade the openvstorage-sdm package
"""

import sys
from datetime import datetime
sys.path.append('/opt/asd-manager')


def _log(message):
    print '{0} - {1}'.format(str(datetime.now()), message)

if __name__ == '__main__':
    from source.tools.filemutex import FileMutex
    from subprocess import check_output

    _log('Upgrading package openvstorage-sdm')
    with FileMutex('package_update'):
        _log('Lock in place, starting upgrade')
        for line in check_output('apt-get install -y --force-yes openvstorage-sdm', shell=True).splitlines():
            _log('  {0}'.format(line))
    _log('Upgrade completed')
