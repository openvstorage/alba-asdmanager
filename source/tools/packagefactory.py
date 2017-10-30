# Copyright (C) 2017 iNuron NV
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
Package Factory module
"""
from ovs_extensions.packages.packagefactory import PackageFactory as _PackageFactory
from source.tools.configuration import Configuration


class PackageFactory(_PackageFactory):
    """
    Factory class returning specialized classes
    """

    universal_packages = ['openvstorage-sdm', 'openvstorage-extensions']
    ose_only_packages = ['alba']
    ee_only_packages = ['alba-ee']

    universal_binaries = []
    ose_only_binaries = ['alba']
    ee_only_binaries = ['alba-ee']

    def __init__(self):
        """
        Initialization method
        """
        pass

    @classmethod
    def _get_packages(cls):
        if Configuration.exists('/ovs/framework/edition'):
            edition = Configuration.get('/ovs/framework/edition')
            if edition == 'community':
                package_names = cls.ose_only_packages
                binaries = cls.ose_only_binaries
            elif edition == 'enterprise':
                package_names = cls.ee_only_packages
                binaries = cls.ee_only_binaries
            else:
                raise ValueError('Edition could not be found in configuration')
        else:
            package_names = cls.ose_only_packages + cls.ee_only_packages
            binaries = cls.ose_only_binaries + cls.ee_only_binaries

        return {'names': package_names + cls.universal_packages,
                'binaries': binaries + cls.universal_binaries}

    @classmethod
    def _get_versions(cls):
        return {'alba': 'alba version --terse'}
