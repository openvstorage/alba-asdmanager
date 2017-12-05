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
Service Factory for the ASD Manager
"""

from ovs_extensions.services.servicefactory import ServiceFactory as _ServiceFactory
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.system import System


class ServiceFactory(_ServiceFactory):
    """
    Service Factory for the ASD Manager
    """
    RUN_FILE_DIR = '/opt/asd-manager/run'
    SERVICE_CONFIG_KEY = '/ovs/alba/asdnodes/{0}/services/{1}'
    CONFIG_TEMPLATE_DIR = '/opt/asd-manager/config/{0}'
    MONITOR_PREFIXES = ['alba-|asd-']

    def __init__(self):
        """Init method"""
        raise Exception('This class cannot be instantiated')

    @classmethod
    def _get_system(cls):
        return System

    @classmethod
    def _get_configuration(cls):
        return Configuration

    @classmethod
    def _get_logger_instance(cls):
        return Logger('tools')
