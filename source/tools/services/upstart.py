# Copyright 2015 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Upstart module
"""

import re
import time
from subprocess import CalledProcessError


class Upstart(object):
    """
    Contains all logic related to Upstart services
    """

    @staticmethod
    def _service_exists(name, client, path=None):
        if path is None:
            path = '/etc/init/'
        file_to_check = '{0}{1}.conf'.format(path, name)
        return client.file_exists(file_to_check)

    @staticmethod
    def _get_service_filename(name, client, path=None):
        if Upstart._service_exists(name, client, path):
            if path is None:
                path = '/etc/init/'
            return '{0}{1}.conf'.format(path, name)
        else:
            return ''

    @staticmethod
    def _get_name(name, client, path=None):
        """
        Make sure that for e.g. 'ovs-workers' the given service name can be either 'ovs-workers' as just 'workers'
        """
        if Upstart._service_exists(name, client, path):
            return name
        if client.file_exists('/etc/init.d/{0}'.format(name)):
            return name
        name = 'ovs-{0}'.format(name)
        if Upstart._service_exists(name, client, path):
            return name
        print('Service {0} could not be found.'.format(name))
        raise ValueError('Service {0} could not be found.'.format(name))

    @staticmethod
    def prepare_template(base_name, target_name, client):
        template_name = '/opt/asd-manager/config/upstart/{0}.conf'
        if client.file_exists(template_name.format(base_name)):
            client.run('cp -f {0} {1}'.format(
                template_name.format(base_name),
                template_name.format(target_name)
            ))

    @staticmethod
    def add_service(name, client, params=None, target_name=None, additional_dependencies=None):
        if params is None:
            params = {}

        name = Upstart._get_name(name, client, '/opt/asd-manager/config/upstart/')
        template_conf = '/opt/asd-manager/config/upstart/{0}.conf'

        if not client.file_exists(template_conf.format(name)):
            # Given template doesn't exist so we are probably using system
            # init scripts
            return

        template_file = client.file_read(template_conf.format(name))

        for key, value in params.iteritems():
            template_file = template_file.replace('<{0}>'.format(key), value)
        if '<SERVICE_NAME>' in template_file:
            service_name = name if target_name is None else target_name
            template_file = template_file.replace('<SERVICE_NAME>', service_name.lstrip('ovs-'))

        dependencies = ''
        if additional_dependencies:
            for service in additional_dependencies:
                dependencies += '{0} '.format(service)
        template_file = template_file.replace('<ADDITIONAL_DEPENDENCIES>', dependencies)

        if target_name is None:
            client.file_write('/etc/init/{0}.conf'.format(name), template_file)
        else:
            client.file_write('/etc/init/{0}.conf'.format(target_name), template_file)

    @staticmethod
    def get_service_status(name, client, return_output=False):
        try:
            name = Upstart._get_name(name, client)
            output = client.run('service {0} status || true'.format(name))
            # Special cases (especially old SysV ones)
            if 'rabbitmq' in name:
                status = re.search('\{pid,\d+?\}', output) is not None
                if return_output is True:
                    return status, output
                return status
            # Normal cases - or if the above code didn't yield an outcome
            if 'start/running' in output or 'is running' in output:
                if return_output is True:
                    return True, output
                return True
            if 'stop' in output or 'not running' in output:
                if return_output is True:
                    return False, output
                return False
            if return_output is True:
                return False, output
            return False
        except CalledProcessError as ex:
            print('Get {0}.service status failed: {1}'.format(name, ex))
            raise Exception('Retrieving status for service "{0}" failed'.format(name))

    @staticmethod
    def remove_service(name, client):
        # remove upstart.conf file
        name = Upstart._get_name(name, client)
        client.file_delete('/etc/init/{0}.conf'.format(name))
        client.file_delete('/etc/init/{0}.override'.format(name))

    @staticmethod
    def disable_service(name, client):
        name = Upstart._get_name(name, client)
        client.run('echo "manual" > /etc/init/{0}.override'.format(name))

    @staticmethod
    def enable_service(name, client):
        name = Upstart._get_name(name, client)
        client.file_delete('/etc/init/{0}.override'.format(name))

    @staticmethod
    def start_service(name, client):
        try:
            name = Upstart._get_name(name, client)
            client.run('service {0} start'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            print('Start {0} failed, {1}'.format(name, output))
            raise RuntimeError('Start {0} failed. {1}'.format(name, output))
        tries = 10
        while tries > 0:
            status, output = Upstart.get_service_status(name, client, True)
            if status is True:
                return output
            tries -= 1
            time.sleep(10 - tries)
        status, output = Upstart.get_service_status(name, client, True)
        if status is True:
            return output
        print('Start {0} failed. {1}'.format(name, output))
        raise RuntimeError('Start {0} failed. {1}'.format(name, output))

    @staticmethod
    def stop_service(name, client):
        try:
            name = Upstart._get_name(name, client)
            client.run('service {0} stop'.format(name))
        except CalledProcessError as cpe:
            output = cpe.output
            print('Stop {0} failed, {1}'.format(name, output))
            raise RuntimeError('Stop {0} failed, {1}'.format(name, output))
        tries = 10
        while tries > 0:
            status, output = Upstart.get_service_status(name, client, True)
            if status is False:
                return output
            tries -= 1
            time.sleep(10 - tries)
        status, output = Upstart.get_service_status(name, client, True)
        if status is False:
            return output
        print('Stop {0} failed. {1}'.format(name, output))
        raise RuntimeError('Stop {0} failed. {1}'.format(name, output))

    @staticmethod
    def restart_service(name, client):
        Upstart.stop_service(name, client)
        return Upstart.start_service(name, client)

    @staticmethod
    def has_service(name, client):
        try:
            Upstart._get_name(name, client)
            return True
        except ValueError:
            return False

    @staticmethod
    def is_enabled(name, client):
        name = Upstart._get_name(name, client)
        if client.file_exists('/etc/init/{0}.override'.format(name)):
            return False
        return True

    @staticmethod
    def get_service_pid(name, client):
        name = Upstart._get_name(name, client)
        if Upstart.get_service_status(name, client):
            output = client.run('service {0} status'.format(name))
            if output:
                # Special cases (especially old SysV ones)
                if 'rabbitmq' in name:
                    match = re.search('\{pid,(?P<pid>\d+?)\}', output)
                else:
                    # Normal cases - or if the above code didn't yield an outcome
                    match = re.search('start/running, process (?P<pid>\d+)', output)
                if match is not None:
                    match_groups = match.groupdict()
                    if 'pid' in match_groups:
                        return match_groups['pid']
        return -1

    @staticmethod
    def list_service_files(client):
        for file in client.dir_list('/etc/init'):
            if file.endswith('.conf'):
                yield file.replace('.conf', '')
