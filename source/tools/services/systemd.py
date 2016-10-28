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
        Systemd._logger.info('Service {0} could not be found.'.format(name))
        raise ValueError('Service {0} could not be found.'.format(name))

    @staticmethod
    def add_service(name, client, params=None, target_name=None, additional_dependencies=None):
        """
        Add a service
        :param name: Name of the service to add
        :type name: str
        :param client: Client on which to add the service
        :type client: SSHClient
        :param params: Additional information about the service
        :type params: dict
        :param target_name: Overrule default name of the service with this name
        :type target_name: str
        :param additional_dependencies: Additional dependencies for this service
        :type additional_dependencies: list
        :return: None
        """
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
    def get_service_status(name, client):
        """
        Retrieve the status of a service
        :param name: Name of the service to retrieve the status of
        :type name: str
        :param client: Client on which to retrieve the status
        :type client: SSHClient
        :return: The status of the service and the output of the command
        :rtype: tuple
        """
        name = Systemd._get_name(name, client)
        output = client.run('systemctl is-active {0} || true'.format(name))
        if output == 'active':
            return True, output
        elif output == 'inactive':
            return False, output
        return False, output

    @staticmethod
    def remove_service(name, client):
        """
        Remove a service
        :param name: Name of the service to remove
        :type name: str
        :param client: Client on which to remove the service
        :type client: SSHClient
        :return: None
        """
        # remove systemd.service file
        name = Systemd._get_name(name, client)
        try:
            client.run('systemctl disable {0}.service')
        except CalledProcessError:
            pass  # Service already disabled
        client.file_delete('/lib/systemd/system/{0}.service'.format(name))
        client.run('systemctl daemon-reload')

    @staticmethod
    def start_service(name, client):
        """
        Start a service
        :param name: Name of the service to start
        :type name: str
        :param client: Client on which to start the service
        :type client: SSHClient
        :return: The output of the start command
        :rtype: str
        """
        status, output = Systemd.get_service_status(name, client)
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
        """
        Stop a service
        :param name: Name of the service to stop
        :type name: str
        :param client: Client on which to stop the service
        :type client: SSHClient
        :return: The output of the stop command
        :rtype: str
        """
        status, output = Systemd.get_service_status(name, client)
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
        """
        Restart a service
        :param name: Name of the service to restart
        :type name: str
        :param client: Client on which to restart the service
        :type client: SSHClient
        :return: The output of the restart command
        :rtype: str
        """
        try:
            name = Systemd._get_name(name, client)
            output = client.run('systemctl restart {0}.service'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            Systemd._logger.exception('Restart {0} failed, {1}'.format(name, output))
        return output

    @staticmethod
    def has_service(name, client):
        """
        Verify existence of a service
        :param name: Name of the service to verify
        :type name: str
        :param client: Client on which to check for the service
        :type client: SSHClient
        :return: Whether the service exists
        :rtype: bool
        """
        try:
            Systemd._get_name(name, client)
            return True
        except ValueError:
            return False

    @staticmethod
    def get_service_pid(name, client):
        """
        Retrieve the PID of a service
        :param name: Name of the service to retrieve the PID for
        :type name: str
        :param client: Client on which to retrieve the PID for the service
        :type client: SSHClient
        :return: The PID of the service or 0 if no PID found
        :rtype: int
        """
        pid = 0
        name = Systemd._get_name(name, client)
        if Systemd.get_service_status(name, client)[0] is True:
            output = client.run('systemctl show {0} --property=MainPID || true'.format(name)).split('=')
            if len(output) == 2:
                pid = output[1]
                if not pid.isdigit():
                    pid = 0
        return int(pid)

    @staticmethod
    def send_signal(name, signal, client):
        """
        Send a signal to a service
        :param name: Name of the service to send a signal
        :type name: str
        :param signal: Signal to pass on to the service
        :type signal: int
        :param client: Client on which to send a signal to the service
        :type client: SSHClient
        :return: None
        """
        name = Systemd._get_name(name, client)
        pid = Systemd.get_service_pid(name, client)
        if pid == 0:
            raise RuntimeError('Could not determine PID to send signal to')
        client.run('kill -s {0} {1}'.format(signal, pid))

    @staticmethod
    def list_services(client):
        """
        List all created services on a system
        :param client: Client on which to list all the services
        :type client: SSHClient
        :return: List of all services which have been created at some point
        :rtype: generator
        """
        for service_info in client.run('systemctl list-unit-files --type=service --no-legend --no-pager').splitlines():
            yield '.'.join(service_info.split(' ')[0].split('.')[:-1])
