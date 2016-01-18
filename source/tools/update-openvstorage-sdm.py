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
Script to install openvstorage-sdm - uses FileMutex('package_update') to
 synchronize with asd-manager api
"""

import sys, datetime, time
sys.path.append('/opt/asd-manager')

from source.tools.filemutex import FileMutex
from subprocess import check_output

def now():
    return str(datetime.datetime.fromtimestamp(time.time()))

print(now(), 'Update script for package openvstorage-sdm')
with FileMutex('package_update'):
    print(now(), 'Locking in place for apt-get install')
    print(now(),
          check_output('apt-get install -y --force-yes openvstorage-sdm',
                        shell=True).splitlines())
print(now(), 'Finished update')
