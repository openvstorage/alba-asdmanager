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
This module contains the generic controller (generic logic)
"""
from subprocess import check_output


class GenericController(object):
    """
    Generic controller class
    """
    @staticmethod
    def collect_logs():
        """
        Retrieve the ALBA and ASD related logs on this node
        :return: The name of the local tar file containing the logs
        :rtype: str
        """
        return check_output('asd-manager collect logs', shell=True).strip()
