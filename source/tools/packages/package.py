# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Package Factory module
"""
import os
from subprocess import check_output
from .debian import DebianPackage
from .rpm import RpmPackage


class PackageManager(object):
    """
    Factory class returning specialized classes
    """
    ImplementationClass = None
    OVS_PACKAGE_NAMES = ['openvstorage-sdm', 'alba', 'arakoon']

    class MetaClass(type):
        """
        Metaclass
        """

        def __getattr__(cls, item):
            """
            Returns the appropriate class
            """
            _ = cls
            if PackageManager.ImplementationClass is None:
                distributor = None
                check_lsb = check_output('which lsb_release 2>&1 || true', shell=True).strip()
                if "no lsb_release in" in check_lsb:
                    if os.path.exists('/etc/centos-release'):
                        distributor = 'CentOS'
                else:
                    distributor = check_output('lsb_release -i', shell=True)
                    distributor = distributor.replace('Distributor ID:', '').strip()
                # All *Package classes used in below code should share the exact same interface!
                if distributor in ['Ubuntu']:
                    PackageManager.ImplementationClass = DebianPackage
                elif distributor in ['CentOS']:
                    PackageManager.ImplementationClass = RpmPackage
                else:
                    raise RuntimeError('There is no handler for Distributor ID: {0}'.format(distributor))
            PackageManager.ImplementationClass.OVS_PACKAGE_NAMES = PackageManager.OVS_PACKAGE_NAMES
            return getattr(PackageManager.ImplementationClass, item)

    __metaclass__ = MetaClass
