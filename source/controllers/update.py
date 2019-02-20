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
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.generic.sshclient import SSHClient
from source.asdmanager import BOOTSTRAP_FILE
from source.constants.asd import ASD_NODE_CONFIG_MAIN_LOCATION
from source.controllers.asd import ASDController
from source.controllers.maintenance import MaintenanceController
from source.dal.lists.settinglist import SettingList
from source.dal.objects.setting import Setting
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.packagefactory import PackageFactory
from source.tools.servicefactory import ServiceFactory
from source.tools.system import System


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
        Whether a service has the correct binary version in use, we use the ServiceFactory.get_service_update_versions functionality

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
                if package_name in [PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE]:
                    for service_name in sorted(list(ASDController.list_asd_services())) + sorted(list(MaintenanceController.get_services())):
                        service_version = ServiceFactory.get_service_update_versions(client=cls._local_client, service_name=service_name, binary_versions=binaries)
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
    def restart_services(cls, service_names, regenerate=False):
        """
        Restart the services specified
        :param service_names: Names of the services to restart
        :type service_names: list[str]
        :return: None
        :rtype: NoneType
        """
        if len(service_names) == 0:
            service_names = [service_name for service_name in ASDController.list_asd_services()]
            service_names.extend([service_name for service_name in MaintenanceController.get_services()])

        for service_name in service_names:
            cls._logger.warning('Verifying whether service {0} needs to be restarted'.format(service_name))
            if cls._service_manager.get_service_status(service_name, cls._local_client) != 'active':
                cls._logger.warning('Found stopped service {0}. Will not start it.'.format(service_name))
                continue

            cls._logger.info('Restarting service {0}'.format(service_name))
            try:
                if regenerate:
                    cls._service_manager.regenerate_service(service_name, cls._local_client)
                else:
                    cls._service_manager.restart_service(service_name, cls._local_client)

            except CalledProcessError:
                cls._logger.exception('Failed to restart service {0}'.format(service_name))

    @classmethod
    def execute_migration_code(cls):
        # type: () -> None
        """
        Run some migration code after an update has been done
        :return: None
        :rtype: NoneType
        """
        cls._logger.info('Starting out of band migrations for SDM nodes')

        ###########################
        # Start crucial migration #
        ###########################

        # Removal of bootstrap file and store API IP, API port and node ID in SQLite DB
        try:
            if cls._local_client.file_exists(BOOTSTRAP_FILE):
                cls._logger.info('Bootstrap file still exists. Retrieving node ID')
                with open(BOOTSTRAP_FILE) as bstr_file:
                    node_id = json.load(bstr_file)['node_id']
            else:
                node_id = SettingList.get_setting_by_code(code='node_id').value
        except Exception:
            cls._logger.exception('Unable to determine the node ID, cannot migrate')
            raise

        try:
            api_settings_map = {'api_ip': 'ip', 'api_port': 'port'}  # Map settings code to keys in the Config management
            required_settings = ['node_id', 'migration_version'] + api_settings_map.keys()
            for settings_code in required_settings:
                try:
                    _ = SettingList.get_setting_by_code(settings_code)
                except ObjectNotFoundException:
                    cls._logger.info('Missing required settings: {0}'.format(settings_code))
                    if settings_code == 'node_id':
                        value = node_id
                    elif settings_code in api_settings_map.keys():
                        # Information must be extracted from Configuration
                        main_config = Configuration.get(ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id))
                        value = main_config[api_settings_map[settings_code]]
                    elif settings_code == 'migration_version':
                        # Introduce version for ASD Manager migration code
                        value = 0
                    else:
                        raise NotImplementedError('No action implemented for setting {0}'.format(settings_code))

                    cls._logger.info('Modeling Setting with code {0} and value {1}'.format(settings_code, value))
                    setting = Setting()
                    setting.code = settings_code
                    setting.value = value
                    setting.save()

            if cls._local_client.file_exists(BOOTSTRAP_FILE):
                cls._logger.info('Removing the bootstrap file')
                cls._local_client.file_delete(BOOTSTRAP_FILE)
        except Exception:
            cls._logger.exception('Error during migration of code settings. Unable to proceed')
            raise

        ###############################
        # Start non-crucial migration #
        ###############################

        errors = []
        migration_setting = SettingList.get_setting_by_code(code='migration_version')
        # Add installed package_name in version files and additional string replacements in service files
        try:
            if migration_setting.value < 1:
                cls._logger.info('Adding additional information to service files')
                edition = Configuration.get_edition()
                if edition == PackageFactory.EDITION_ENTERPRISE:
                    for version_file_name in cls._local_client.file_list(directory=ServiceFactory.RUN_FILE_DIR):
                        version_file_path = '{0}/{1}'.format(ServiceFactory.RUN_FILE_DIR, version_file_name)
                        contents = cls._local_client.file_read(filename=version_file_path)
                        if '{0}='.format(PackageFactory.PKG_ALBA) in contents:
                            contents = contents.replace(PackageFactory.PKG_ALBA, PackageFactory.PKG_ALBA_EE)
                            cls._local_client.file_write(filename=version_file_path, contents=contents)

                    node_id = SettingList.get_setting_by_code(code='node_id').value
                    asd_services = list(ASDController.list_asd_services())
                    maint_services = list(MaintenanceController.get_services())
                    for service_name in asd_services + maint_services:
                        config_key = ServiceFactory.SERVICE_CONFIG_KEY.format(node_id, service_name)
                        if Configuration.exists(key=config_key):
                            config = Configuration.get(key=config_key)
                            if 'RUN_FILE_DIR' in config:
                                continue
                            config['RUN_FILE_DIR'] = ServiceFactory.RUN_FILE_DIR
                            config['ALBA_PKG_NAME'] = PackageFactory.PKG_ALBA_EE
                            config['ALBA_VERSION_CMD'] = PackageFactory.VERSION_CMD_ALBA
                            Configuration.set(key=config_key, value=config)
                            cls._service_manager.regenerate_service(name=ASDController.ASD_PREFIX if service_name in asd_services else MaintenanceController.MAINTENANCE_PREFIX,
                                                                    client=cls._local_client,
                                                                    target_name=service_name)
        except Exception as ex:
            cls._logger.exception('Failed to regenerate the ASD and Maintenance services')
            errors.append(ex)

        try:
            if migration_setting.value < 2:
                if System.get_component_identifier() not in Configuration.get(Configuration.get_registration_key(), default=[]):
                    Configuration.register_usage(System.get_component_identifier())
        except Exception as ex:
            cls._logger.exception('Failed to register the asd-manager')
            errors.append(ex)

        if len(errors) == 0:
            cls._logger.info('No errors during non-crucial migration. Saving the migration setting')
            # Save migration settings when no errors occurred
            migration_setting = SettingList.get_setting_by_code(code='migration_version')
            migration_setting.value = 2
            migration_setting.save()

        cls._logger.info('Finished out of band migrations for SDM nodes')
