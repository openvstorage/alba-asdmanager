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
import os
import json
from ovs_extensions.generic.sshclient import SSHClient
from source.tools.configuration import Configuration
from source.tools.log_handler import LogHandler
from source.tools.servicefactory import ServiceFactory


class MaintenanceController(object):
    """
    Maintenance controller class
    """
    MAINTENANCE_PREFIX = 'alba-maintenance'
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _service_manager = ServiceFactory.get_manager()

    @staticmethod
    def get_services():
        """
        Retrieve all configured maintenance service running on this node for each backend
        :return: generator
        """
        for service_name in MaintenanceController._service_manager.list_services(MaintenanceController._local_client):
            if service_name.startswith(MaintenanceController.MAINTENANCE_PREFIX):
                yield service_name

    @staticmethod
    def add_maintenance_service(name, backend_guid, abm_name):
        """
        Add a maintenance service with a specific name
        :param name: Name of the service to add
        :type name: str
        :param backend_guid: Backend for which the maintenance service needs to run
        :type backend_guid: str
        :param abm_name: Name of the ABM cluster
        :type abm_name: str
        """
        if MaintenanceController._service_manager.has_service(name, MaintenanceController._local_client) is False:
            config_location = '/ovs/alba/backends/{0}/maintenance/config'.format(backend_guid)
            alba_config = Configuration.get_configuration_path(config_location)
            node_id = os.environ.get('ASD_NODE_ID')
            params = {'ALBA_CONFIG': alba_config,
                      'LOG_SINK': LogHandler.get_sink_path('alba_maintenance')}
            Configuration.set(config_location, json.dumps({
                'log_level': 'info',
                'albamgr_cfg_url': Configuration.get_configuration_path('/ovs/arakoon/{0}/config'.format(abm_name)),
                'read_preference': [] if node_id is None else [node_id]
            }, indent=4), raw=True)

            MaintenanceController._service_manager.add_service(name=MaintenanceController.MAINTENANCE_PREFIX,
                                                               client=MaintenanceController._local_client,
                                                               params=params,
                                                               target_name=name)
        MaintenanceController._service_manager.start_service(name, MaintenanceController._local_client)

    @staticmethod
    def remove_maintenance_service(name):
        """
        Remove a maintenance service with a specific name
        :param name: Name of the service
        """
        if MaintenanceController._service_manager.has_service(name, MaintenanceController._local_client):
            MaintenanceController._service_manager.stop_service(name, MaintenanceController._local_client)
            MaintenanceController._service_manager.remove_service(name, MaintenanceController._local_client)
