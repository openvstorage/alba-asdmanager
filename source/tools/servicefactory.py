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
from source.tools.packagefactory import PackageFactory
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

    @classmethod
    def get_services_with_version_files(cls, storagerouter=None):
        """
        Retrieve the services which have a version file in RUN_FILE_DIR
        This takes the components into account defined in the PackageFactory for this repository
        :param storagerouter: The StorageRouter for which to retrieve the services with a version file
        :type storagerouter: StorageRouter
        :return: Services split up by component and related package with a version file
                 {<component>: <pkg_name>: {10: [<service1>, <service2>] } } }
        :rtype: dict
        """
        # Import here to prevent from circular references
        from source.controllers.asd import ASDController
        from source.controllers.maintenance import MaintenanceController

        # Retrieve the services which need to be checked for a restart
        _ = storagerouter
        service_info = {}
        for component, package_names in PackageFactory.get_package_info()['names'].iteritems():
            service_info[component] = {}
            for package_name in package_names:
                if package_name in [PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE]:
                    services = {10: list(ASDController.list_asd_services()) + list(MaintenanceController.get_services())}
                else:
                    services = {}
                service_info[component][package_name] = services
        return service_info
