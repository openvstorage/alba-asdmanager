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
import os
import time
from subprocess import CalledProcessError
from source.tools.localclient import LocalClient
from source.tools.log_handler import LogHandler
from source.tools.packages.package import PackageManager
from source.tools.services.service import ServiceManager


class UpdateController(object):
    NODE_ID = os.environ['ASD_NODE_ID']
    PACKAGE_NAME = 'openvstorage-sdm'
    ASD_SERVICE_PREFIX = 'alba-asd-'
    INSTALL_SCRIPT = '/opt/asd-manager/source/tools/install/upgrade-package.py'

    _local_client = LocalClient()
    _logger = LogHandler.get('asd-manager', name='update')

    @staticmethod
    def get_package_information(package_name):
        installed, candidate = PackageManager.get_installed_candidate_version(package_name,
                                                                              UpdateController._local_client)
        UpdateController._logger.info('Installed version for package {0}: {1}'.format(package_name, installed))
        UpdateController._logger.info('Candidate version for package {0}: {1}'.format(package_name, candidate))
        return installed, candidate

    @staticmethod
    def get_sdm_services():
        services = {}
        for service_name in ServiceManager.list_services(UpdateController._local_client):
            if service_name.startswith(UpdateController.ASD_SERVICE_PREFIX):
                file_path = '/opt/asd-manager/run/{0}.version'.format(service_name)
                if os.path.isfile(file_path):
                    with open(file_path) as fp:
                        services[service_name] = fp.read().strip()
        return services

    @staticmethod
    def update_package_cache():
        counter = 0
        max_counter = 3
        while True and counter < max_counter:
            counter += 1
            try:
                PackageManager.update(UpdateController._local_client)
                break
            except CalledProcessError as cpe:
                time.sleep(3)
                if counter == max_counter:
                    raise cpe

    @staticmethod
    def get_update_information():
        UpdateController.update_package_cache()
        sdm_package_info = UpdateController.get_package_information(package_name=UpdateController.PACKAGE_NAME)
        sdm_installed = sdm_package_info[0]
        sdm_candidate = sdm_package_info[1]
        if sdm_installed != sdm_candidate:
            return {'version': sdm_candidate,
                    'installed': sdm_installed}
        alba_package_info = UpdateController.get_package_information(package_name='alba')
        services = [key for key, value in UpdateController.get_sdm_services().iteritems() if value != alba_package_info[1]]
        return {'version': sdm_candidate if services else '',
                'installed': sdm_installed}

    @staticmethod
    def execute_update(status):
        try:
            UpdateController.update_package_cache()
            sdm_package_info = UpdateController.get_package_information(package_name=UpdateController.PACKAGE_NAME)
        except CalledProcessError:
            return {'status': 'started'}

        if sdm_package_info[0] != sdm_package_info[1]:
            if status == 'started':
                UpdateController._logger.info('Updating package {0}'.format(UpdateController.PACKAGE_NAME))
                UpdateController._local_client.run('echo "ASD_NODE_ID={0} python {1} >> /var/log/upgrade-openvstorage-sdm.log 2>&1" > /tmp/update'.format(UpdateController.NODE_ID, UpdateController.INSTALL_SCRIPT), allow_insecure=True)
                UpdateController._local_client.run(['at', '-f', '/tmp/update now'])
                UpdateController._local_client.run(['rm', '/tmp/update'])
            return {'status': 'running'}
        else:
            status, _ = ServiceManager.get_service_status('asd-manager', UpdateController._local_client)
            return {'status': 'done' if status is True else 'running'}

    @staticmethod
    def restart_services():
        UpdateController.update_package_cache()
        alba_package_info = UpdateController.get_package_information(package_name='alba')
        result = {}
        for service, running_version in UpdateController.get_sdm_services().iteritems():
            if running_version != alba_package_info[1]:
                status, _ = ServiceManager.get_service_status(service, UpdateController._local_client)
                if status is False:
                    UpdateController._logger.info('Found stopped service {0}. Will not start it.'.format(service))
                    result[service] = 'stopped'
                else:
                    UpdateController._logger.info('Restarting service {0}'.format(service))
                    try:
                        status = ServiceManager.restart_service(service, UpdateController._local_client)
                        UpdateController._logger.info(status)
                        result[service] = 'restarted'
                    except CalledProcessError as cpe:
                        UpdateController._logger.info('Failed to restart service {0} {1}'.format(service, cpe))
                        result[service] = 'failed'

        return {'result': result}
