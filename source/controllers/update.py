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
This module contains logic related to updates
"""

import json
from subprocess import CalledProcessError
from ovs_extensions.generic.sshclient import SSHClient
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from source.controllers.asd import ASDController
from source.controllers.maintenance import MaintenanceController
from source.dal.lists.settinglist import SettingList
from source.dal.objects.setting import Setting
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.packagefactory import PackageFactory
from source.tools.servicefactory import ServiceFactory


class SDMUpdateController(object):
    """
    Update Controller class for SDM package
    """
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _logger = Logger(name='update', forced_target_type='file')
    _package_manager = PackageFactory.get_manager()
    _service_manager = ServiceFactory.get_manager()

    @classmethod
    def get_package_information(cls):
        """
        Called by GenericController.refresh_package_information() every hour

        Retrieve information about the currently installed versions of the core packages
        Retrieve information about the versions to which each package can potentially be updated
        If installed version is different from candidate version --> store this information in model

        Additionally if installed version is identical to candidate version, check the services with a 'run' file
        Verify whether the running version is identical to the candidate version
        If different --> store this information in the model

        Result: Every package with updates or which requires services to be restarted is stored in the model

        :return: Package information
        :rtype: dict
        """
        binaries = cls._package_manager.get_binary_versions(client=cls._local_client)
        service_info = ServiceFactory.get_services_with_version_files()
        packages_to_update = PackageFactory.get_packages_to_update(client=cls._local_client)
        services_to_update = ServiceFactory.get_services_to_update(client=cls._local_client,
                                                                   binaries=binaries,
                                                                   service_info=service_info)

        # First we merge in the services
        package_info = ExtensionsToolbox.merge_dicts(dict1={},
                                                     dict2=services_to_update)
        # Then the packages merge can potentially overrule the installed/candidate version, because these versions need priority over the service versions
        package_info = ExtensionsToolbox.merge_dicts(dict1=package_info,
                                                     dict2=packages_to_update)
        return package_info

    @classmethod
    def update(cls, package_name):
        """
        Update the package on the local node
        :return: None
        :rtype: NoneType
        """
        cls._logger.info('Installing package {0}'.format(package_name))
        cls._package_manager.install(package_name=package_name, client=cls._local_client)
        cls._logger.info('Installed package {0}'.format(package_name))

    @classmethod
    def get_installed_version_for_package(cls, package_name):
        """
        Retrieve the currently installed package version
        :param package_name: Name of the package to retrieve the version for
        :type package_name: str
        :return: Version of the currently installed package
        :rtype: str
        """
        installed_version = cls._package_manager.get_installed_versions(client=None, package_names=[package_name])
        if package_name in installed_version:
            return str(installed_version[package_name])

    @classmethod
    def restart_services(cls):
        """
        Restart the services ASD services and the Maintenance services
        :return: None
        :rtype: NoneType
        """
        service_names = [service_name for service_name in ASDController.list_asd_services()]
        service_names.extend([service_name for service_name in MaintenanceController.get_services()])
        for service_name in service_names:
            if cls._service_manager.get_service_status(service_name, cls._local_client) != 'active':
                cls._logger.warning('Found stopped service {0}. Will not start it.'.format(service_name))
                continue

            cls._logger.info('Restarting service {0}'.format(service_name))
            try:
                cls._service_manager.restart_service(service_name, cls._local_client)
            except CalledProcessError:
                cls._logger.exception('Failed to restart service {0}'.format(service_name))

    @classmethod
    def execute_migration_code(cls):
        """
        Run some migration code after an update has been done
        :return: None
        :rtype: NoneType
        """
        # Removal of bootstrap file and store API IP, API port and node ID in SQLite DB
        cls._logger.info('Starting out of band migrations for SDM nodes')

        required_settings = ['api_ip', 'api_port', 'node_id']
        for setting in SettingList.get_settings():
            if setting.code in required_settings:
                required_settings.remove(setting.code)

        if len(required_settings):
            cls._logger.info('Missing required Settings: {0}'.format(', '.join(required_settings)))
            bootstrap_file = '/opt/asd-manager/config/bootstrap.json'

            if cls._local_client.file_exists(bootstrap_file):
                cls._logger.info('Bootstrap file still exists. Retrieving node ID')
                with open(bootstrap_file) as bstr_file:
                    node_id = json.load(bstr_file)['node_id']
            else:
                node_id = SettingList.get_setting_by_code(code='node_id').value

            cls._logger.info('Node ID: {0}'.format(node_id))
            settings_dict = {'node_id': node_id}
            if Configuration.exists(Configuration.ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id)):
                main_config = Configuration.get(Configuration.ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id))
                settings_dict['api_ip'] = main_config['ip']
                settings_dict['api_port'] = main_config['port']

            for code, value in settings_dict.iteritems():
                cls._logger.info('Modeling Setting with code {0} and value {1}'.format(code, value))
                setting = Setting()
                setting.code = code
                setting.value = value
                setting.save()

            cls._local_client.file_delete(bootstrap_file)
        cls._logger.info('Finished out of band migrations for SDM nodes')
