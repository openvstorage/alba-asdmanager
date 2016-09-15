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
Systemd module
"""
from subprocess import CalledProcessError
from source.tools.log_handler import LogHandler


class Systemd(object):
    """
    Contains all logic related to Systemd services
    """

    _logger = LogHandler.get('asd-manager', name='systemd')

    @staticmethod
    def _service_exists(name, client, path):
        if path is None:
            path = '/lib/systemd/system/'
        file_to_check = '{0}{1}.service'.format(path, name)
        return client.file_exists(file_to_check)

    @staticmethod
    def _get_name(name, client, path=None):
        """
        Make sure that for e.g. 'ovs-workers' the given service name can be either 'ovs-workers' as just 'workers'
        """
        if Systemd._service_exists(name, client, path):
            return name
        if Systemd._service_exists(name, client, '/lib/systemd/system/'):
            return name
        name = 'ovs-{0}'.format(name)
        if Systemd._service_exists(name, client, path):
            return name
        Systemd._logger.debug('Service {0} could not be found.'.format(name))
        raise ValueError('Service {0} could not be found.'.format(name))

    @staticmethod
    def add_service(name, client, params=None, target_name=None, additional_dependencies=None):
        if params is None:
            params = {}

        name = Systemd._get_name(name, client, '/opt/asd-manager/config/systemd/')
        template_service = '/opt/asd-manager/config/systemd/{0}.service'

        if not client.file_exists(template_service.format(name)):
            # Given template doesn't exist so we are probably using system
            # init scripts
            return

        template_file = client.file_read(template_service.format(name))

        for key, value in params.iteritems():
            template_file = template_file.replace('<{0}>'.format(key), value)
        if '<SERVICE_NAME>' in template_file:
            service_name = name if target_name is None else target_name
            template_file = template_file.replace('<SERVICE_NAME>', service_name.lstrip('ovs-'))
        template_file = template_file.replace('<_SERVICE_SUFFIX_>', '')

        dependencies = ''
        if additional_dependencies:
            for service in additional_dependencies:
                dependencies += '{0}.service '.format(service)
        template_file = template_file.replace('<ADDITIONAL_DEPENDENCIES>', dependencies)

        if target_name is None:
            client.file_write('/lib/systemd/system/{0}.service'.format(name), template_file)
        else:
            client.file_write('/lib/systemd/system/{0}.service'.format(target_name), template_file)
            name = target_name

        try:
            client.run('systemctl daemon-reload')
            client.run('systemctl enable {0}.service'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            Systemd._logger.exception('Add {0}.service failed, {1}'.format(name, output))
            raise Exception('Add {0}.service failed, {1}'.format(name, output))

    @staticmethod
    def get_service_status(name, client, return_output=False):
        name = Systemd._get_name(name, client)
        output = client.run('systemctl is-active {0} || true'.format(name))
        if 'active' == output:
            if return_output is True:
                return True, output
            return True
        if 'inactive' == output:
            if return_output is True:
                return False, output
            return False
        if return_output is True:
            return False, output
        return False

    @staticmethod
    def remove_service(name, client):
        # remove systemd.service file
        name = Systemd._get_name(name, client)
        client.file_delete('/lib/systemd/system/{0}.service'.format(name))
        client.run('systemctl daemon-reload')

    @staticmethod
    def disable_service(name, client):
        name = Systemd._get_name(name, client)
        try:
            client.run('systemctl disable {0}.service'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            Systemd._logger.exception('Disable {0} failed, {1}'.format(name, output))
            raise Exception('Disable {0} failed, {1}'.format(name, output))

    @staticmethod
    def enable_service(name, client):
        name = Systemd._get_name(name, client)
        try:
            client.run('systemctl enable {0}.service'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            Systemd._logger.exception('Enable {0} failed, {1}'.format(name, output))
            raise Exception('Enable {0} failed, {1}'.format(name, output))

    @staticmethod
    def start_service(name, client):
        status, output = Systemd.get_service_status(name, client, True)
        if status is True:
            return output
        try:
            name = Systemd._get_name(name, client)
            output = client.run('systemctl start {0}.service'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            Systemd._logger.exception('Start {0} failed, {1}'.format(name, output))
        return output

    @staticmethod
    def stop_service(name, client):
        status, output = Systemd.get_service_status(name, client, True)
        if status is False:
            return output
        try:
            name = Systemd._get_name(name, client)
            output = client.run('systemctl stop {0}.service'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            Systemd._logger.exception('Stop {0} failed, {1}'.format(name, output))
        return output

    @staticmethod
    def restart_service(name, client):
        try:
            name = Systemd._get_name(name, client)
            output = client.run('systemctl restart {0}.service'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            Systemd._logger.exception('Restart {0} failed, {1}'.format(name, output))
        return output

    @staticmethod
    def has_service(name, client):
        try:
            Systemd._get_name(name, client)
            return True
        except ValueError:
            return False

    @staticmethod
    def is_enabled(name, client):
        name = Systemd._get_name(name, client)
        output = client.run('systemctl is-enabled {0} || true'.format(name))
        if 'enabled' in output:
            return True
        if 'disabled' in output:
            return False
        return False

    @staticmethod
    def get_service_pid(name, client):
        pid = 0
        name = Systemd._get_name(name, client)
        if Systemd.get_service_status(name, client):
            output = client.run('systemctl status {0} || true'.format(name))
            if output:
                output = output.splitlines()
                for line in output:
                    if 'Main PID' in line:
                        pid = line.split(' ')[3]
                        if not pid.isdigit():
                            pid = 0
                        break
        return pid

    @staticmethod
    def send_signal(name, signal, client):
        pid = Systemd.get_service_pid(name, client)
        if pid == 0:
            raise RuntimeError('Could not determine PID to send signal to')
        client.run('kill -s {0} {1}'.format(signal, pid))

    @staticmethod
    def list_services(client):
        for service_info in client.run('systemctl list-unit-files --type=service --no-legend --no-pager'):
            yield service_info.split(' ')[0].rtrim('.service')
