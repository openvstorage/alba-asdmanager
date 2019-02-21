# Copyright (C) 2016 iNuron NV
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
This module contains the maintenance controller (maintenance service logic)
"""

from ovs_extensions.generic.sshclient import SSHClient
from ovs_extensions.constants.arakoon import ARAKOON_CONFIG
from ovs_extensions.constants.alba import BACKEND_MAINTENANCE_CONFIG, BACKEND_MAINTENANCE_SERVICE, MAINTENANCE_PREFIX
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.packagefactory import PackageFactory
from source.tools.servicefactory import ServiceFactory


class MaintenanceController(object):
    """
    Maintenance controller class
    """
    MAINTENANCE_KEY = BACKEND_MAINTENANCE_SERVICE
    MAINTENANCE_PREFIX = MAINTENANCE_PREFIX
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _service_manager = ServiceFactory.get_manager()

    @staticmethod
    def get_services():
        """
        Retrieve all configured maintenance services running on this node for each backend
        :return: The maintenance services present on this ALBA Node
        :rtype: generator
        """
        for service_name in MaintenanceController._service_manager.list_services(MaintenanceController._local_client):
            if service_name.startswith(MAINTENANCE_PREFIX):
                yield service_name

    @staticmethod
    def add_maintenance_service(name, alba_backend_guid, abm_name, read_preferences=None):
        """
        Add a maintenance service with a specific name
        :param name: Name of the maintenance service to add
        :type name: str
        :param alba_backend_guid: ALBA Backend GUID for which the maintenance service needs to run
        :type alba_backend_guid: str
        :param abm_name: Name of the ABM cluster
        :type abm_name: str
        :param read_preferences: List of ALBA Node IDs (LOCAL) or ALBA IDs of linked ALBA Backends (GLOBAL) for the maintenance services where they should prioritize the READ actions
        :type read_preferences: list[str]
        :return: None
        :rtype: NoneType
        """
        if MaintenanceController._service_manager.has_service(name, MaintenanceController._local_client) is False:
            alba_pkg_name, alba_version_cmd = PackageFactory.get_package_and_version_cmd_for(component=PackageFactory.COMP_ALBA)
            config_location = BACKEND_MAINTENANCE_CONFIG.format(alba_backend_guid, name)
            params = {'LOG_SINK': Logger.get_sink_path('alba_maintenance'),
                      'ALBA_CONFIG': Configuration.get_configuration_path(config_location),
                      'ALBA_PKG_NAME': alba_pkg_name,
                      'ALBA_VERSION_CMD': alba_version_cmd}
            Configuration.set(key=config_location,
                              value={'log_level': 'info',
                                     'albamgr_cfg_url': Configuration.get_configuration_path(ARAKOON_CONFIG.format(abm_name)),
                                     'read_preference': [] if read_preferences is None else read_preferences,
                                     'multicast_discover_osds': False})

            MaintenanceController._service_manager.add_service(name=MAINTENANCE_PREFIX,
                                                               client=MaintenanceController._local_client,
                                                               params=params,
                                                               target_name=name)
        MaintenanceController._service_manager.start_service(name, MaintenanceController._local_client)

    @staticmethod
    def remove_maintenance_service(name, alba_backend_guid=None):
        """
        Remove a maintenance service with a specific name
        :param name: Name of the service to remove
        :type name: str
        :param alba_backend_guid: ALBA Backend GUID for which the maintenance service needs to be removed
                                  Defaults to None for backwards compatibility
        :type alba_backend_guid: str
        :return: None
        :rtype: NoneType
        """
        if MaintenanceController._service_manager.has_service(name, MaintenanceController._local_client):
            MaintenanceController._service_manager.stop_service(name, MaintenanceController._local_client)
            MaintenanceController._service_manager.remove_service(name, MaintenanceController._local_client)

        if alba_backend_guid is not None:
            key = BACKEND_MAINTENANCE_SERVICE.format(alba_backend_guid, name)
            if Configuration.dir_exists(key=key):
                Configuration.delete(key=key)
