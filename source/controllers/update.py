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

import copy
import json
from subprocess import CalledProcessError
from ovs_extensions.generic.sshclient import SSHClient
from source.asdmanager import BOOTSTRAP_FILE
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
        Retrieve the installed and candidate versions of all packages relevant for this repository (See PackageFactory.get_package_info)
        If installed version is lower than candidate version, this information is stored
        If installed version is equal or higher than candidate version we verify whether all relevant services have the correct binary active
        Whether a service has the correct binary version in use, we use the ServiceFactory.verify_restart_required functionality

        In this function the services for each component / package combination are defined
        This service information consists out of:
            * Services to stop (before update) and start (after update of packages) -> 'services_stop_start'
            * Services to restart after update (post-update logic)                  -> 'services_post_update'
            * Down-times which will be caused due to service restarts               -> 'downtime'
            * Prerequisites that have not been met                                  -> 'prerequisites'

        The installed vs candidate version which is displayed always gives priority to the versions effectively installed on the system
        and not the versions as reported by the service files

        This combined information is then stored in the 'package_information' of the ALBA Node DAL object
        :return: Update information
        :rtype: dict
        """
        cls._logger.info('Refreshing update information')

        binaries = cls._package_manager.get_binary_versions(client=cls._local_client)
        update_info = {}
        package_info = PackageFactory.get_packages_to_update(client=cls._local_client)  # {'alba': {'openvstorage-sdm': {'installed': 'ee-1.6.1', 'candidate': 'ee-1.6.2'}}}
        cls._logger.debug('Binary versions found: {0}'.format(binaries))
        cls._logger.debug('Package info found: {0}'.format(package_info))
        for component, package_names in PackageFactory.get_package_info()['names'].iteritems():
            package_names = sorted(package_names)
            cls._logger.debug('Validating component {0} and related packages: {1}'.format(component, package_names))
            if component not in update_info:
                update_info[component] = copy.deepcopy(ServiceFactory.DEFAULT_UPDATE_ENTRY)
            svc_component_info = update_info[component]
            pkg_component_info = package_info.get(component, {})

            for package_name in package_names:
                cls._logger.debug('Validating package {0}'.format(package_name))
                if package_name == PackageFactory.PKG_MGR_SDM and package_name in pkg_component_info:
                    cls._logger.debug('Adding ASD watcher service to post-update services')
                    svc_component_info['services_post_update'][10].append('asd-watcher')  # Watcher restarts manager service too
                elif package_name in [PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE]:
                    for service_name in sorted(list(ASDController.list_asd_services())) + sorted(list(MaintenanceController.get_services())):
                        service_version = ServiceFactory.verify_restart_required(client=cls._local_client, service_name=service_name, binary_versions=binaries)
                        cls._logger.debug('Service {0} has version: {1}'.format(service_name, service_version))
                        # If package_name in pkg_component_info --> update available (installed <--> candidate)
                        # If service_version is not None --> service is running an older binary version
                        if package_name in pkg_component_info or service_version is not None:
                            svc_component_info['services_post_update'][20].append(service_name)
                            if service_version is not None and package_name not in svc_component_info['packages']:
                                svc_component_info['packages'][package_name] = service_version

                # Extend the service information with the package information related to this repository for current ALBA Node
                if package_name in pkg_component_info and package_name not in svc_component_info['packages']:
                    cls._logger.debug('Adding package {0} because it has an update available'.format(package_name))
                    svc_component_info['packages'][package_name] = pkg_component_info[package_name]
        cls._logger.info('Refreshed update information')
        return update_info

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
            if cls._local_client.file_exists(BOOTSTRAP_FILE):
                cls._logger.info('Bootstrap file still exists. Retrieving node ID')
                with open(BOOTSTRAP_FILE) as bstr_file:
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

            cls._local_client.file_delete(BOOTSTRAP_FILE)
        cls._logger.info('Finished out of band migrations for SDM nodes')
