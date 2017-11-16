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
Package Factory module for ALBA Manager
"""

from ovs_extensions.packages.packagefactory import PackageFactory as _PackageFactory
from source.tools.configuration import Configuration


class PackageFactory(_PackageFactory):
    """
    Factory class returning specialized classes
    """
    SUPPORTED_COMPONENTS = {_PackageFactory.COMP_ALBA}  # Used by PackageFactory in ovs_extensions for validation

    def __init__(self):
        """
        Initialization method
        """
        super(PackageFactory, self).__init__()

    @classmethod
    def get_package_info(cls):
        """
        Retrieve the package information related to the ASD Manager
        This must return a dictionary with keys: 'names', 'edition', 'binaries', 'blocking', 'version_commands' and 'mutually_exclusive'
            Names: These are the names of the packages split up per component related to this repository (alba-asdmanager)
                * Alba
                    * PKG_MGR_SDM        --> The code itself to deploy and run the ASD Manager
                    * PKG_ALBA(_EE)      --> ASDs and maintenance agents rely on the ALBA Binary
                    * PKG_OVS_EXTENSIONS --> Extensions code is used by the alba-asdmanager
            Edition: Used for different purposes
            Binaries: The names of the packages that come with a binary (also split up per component)
            Blocking: Update will stop (block) in case the update fails for any of these packages
            Version_commands: The commandos used to determine which binary version is currently active
            Mutually_exclusive: Packages which are not allowed to be installed depending on the edition. Eg: ALBA_EE cannot be installed on a 'community' edition
        :raises ValueError: * When configuration management key 'ovs/framework/edition' does not exists
                            * When 'ovs/framework/edition' does not contain 'community' or 'enterprise'
        :return: A dictionary containing information about the expected packages to be installed
        :rtype: dict
        """
        edition_key = '/ovs/framework/edition'
        if Configuration.exists(key=edition_key) is False:
            raise ValueError('Edition configuration key "{0}" does not exist'.format(edition_key))

        edition = str(Configuration.get(key=edition_key))
        if edition == 'community':
            return {'names': {cls.COMP_ALBA: {cls.PKG_MGR_SDM, cls.PKG_ALBA, cls.PKG_OVS_EXTENSIONS}},
                    'edition': edition,
                    'binaries': {cls.COMP_ALBA: {cls.PKG_ALBA}},
                    'blocking': {cls.PKG_MGR_SDM, cls.PKG_OVS_EXTENSIONS},
                    'version_commands': {cls.PKG_ALBA: cls.VERSION_CMD_ALBA},
                    'mutually_exclusive': {cls.PKG_ALBA_EE}}
        elif edition == 'enterprise':
            return {'names': {cls.COMP_ALBA: {cls.PKG_MGR_SDM, cls.PKG_ALBA_EE, cls.PKG_OVS_EXTENSIONS}},
                    'edition': edition,
                    'binaries': {cls.COMP_ALBA: {cls.PKG_ALBA_EE}},
                    'blocking': {cls.PKG_MGR_SDM, cls.PKG_OVS_EXTENSIONS},
                    'version_commands': {cls.PKG_ALBA_EE: cls.VERSION_CMD_ALBA},
                    'mutually_exclusive': {cls.PKG_ALBA}}
        else:
            raise ValueError('Unsupported edition found in "{0}"'.format(edition_key))
