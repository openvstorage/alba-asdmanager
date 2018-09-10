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
System module for the ASD Manager
"""

from ovs_extensions.generic.system import System as _System
from source.dal.lists.settinglist import SettingList


class System(_System):
    """
    System class for the ASD Manager
    """

    def __init__(self):
        """
        Dummy init method
        """
        _ = self

    @classmethod
    def get_my_machine_id(cls, client=None):
        """
        Returns unique machine id, generated during the package install of the ASD Manager
        :param client: Local client on which to retrieve the machine ID
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: Machine ID
        :rtype: str
        """

        return SettingList.get_setting_by_code(code='node_id').value

    @staticmethod
    def get_component_identifier():
        # type: () -> str
        """
        Retrieve the identifier of the component
        :return: The ID of the component
        :rtype: str
        """
        return 'asd-manager'
