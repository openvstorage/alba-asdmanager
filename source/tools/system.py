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
import json
from ovs_extensions.generic.system import System as _System

BOOTSTRAP_FILE = '/opt/asd-manager/config/bootstrap.json'


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
        Returns unique machine id, generated during the setup of the ASD Manager
        :param client: Local client on which to retrieve the machine ID
        :type client: SSHClient
        :return: Machine ID
        :rtype: str
        """
        with open(BOOTSTRAP_FILE) as bs_file:
            return json.loads(bs_file.read())['node_id']
