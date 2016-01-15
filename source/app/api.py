# Copyright 2014 iNuron NV
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
API views
"""

import os
import json
import time
import random
import string
import datetime
from flask import request
from source.app.decorators import get
from source.app.decorators import post
from source.app.exceptions import BadRequest
from source.tools.disks import Disks
from source.tools.filemutex import FileMutex
from source.tools.configuration import EtcdConfiguration
from subprocess import check_output
from subprocess import CalledProcessError


class API(object):
    """ ALBA API """
    PACKAGE_NAME = 'openvstorage-sdm'
    SERVICE_PREFIX = 'alba-asd-'
    APT_CONFIG_STRING = '-o Dir::Etc::sourcelist="sources.list.d/ovsaptrepo.list" -o Dir::Etc::sourceparts="-" -o APT::Get::List-Cleanup="0"'
    INSTALL_SCRIPT = "/opt/alba-asdmanager/source/tools/update-openvstorage-sdm.py"
    ASD_CONFIG_ROOT = '/ovs/alba/asds/{0}/config'
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'
    NODE_ID = 'xxxxxxxxxx'

    @staticmethod
    @get('/')
    def index():
        """ Return available API calls """
        return {'node_id': API.NODE_ID,
                '_links': ['/disks', '/net', '/update'],
                '_actions': []}

    @staticmethod
    @get('/net', authenticate=False)
    def net():
        """ Retrieve IP information """
        print '{0} - Loading network information'.format(datetime.datetime.now())
        output = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True)
        my_ips = output.split('\n')
        return {'ips': [found_ip.strip() for found_ip in my_ips if found_ip.strip() != '127.0.0.1' and found_ip.strip() != ''],
                '_links': [],
                '_actions': ['/net']}

    @staticmethod
    @post('/net')
    def set_net():
        """ Set IP information """
        print '{0} - Setting network information'.format(datetime.datetime.now())
        EtcdConfiguration.set('{0}/main|ips'.format(API.CONFIG_ROOT.format(API.NODE_ID)), json.loads(request.form['ips']))
        return {'_link': '/net'}

    @staticmethod
    def _disk_hateoas(disk, disk_id):
        disk['_link'] = '/disks/{0}'.format(disk_id)
        if disk['available'] is False:
            actions = ['/disks/{0}/delete'.format(disk_id)]
            if disk['state']['state'] == 'error':
                actions.append('/disks/{0}/restart'.format(disk_id))
        else:
            actions = ['/disks/{0}/add'.format(disk_id)]
        disk['_actions'] = actions

    @staticmethod
    def _list_disks():
        print '{0} - Fetching disks'.format(datetime.datetime.now())
        disks = Disks.list_disks()
        for disk_id in disks:
            if disks[disk_id]['available'] is False:
                asd_id = disks[disk_id]['asd_id']
                if disks[disk_id]['state']['state'] != 'error':
                    if os.path.exists('/mnt/alba-asd/{0}/asd.json'.format(asd_id)):
                        try:
                            with open('/mnt/alba-asd/{0}/asd.json'.format(asd_id), 'r') as conffile:
                                disks[disk_id].update(json.load(conffile))
                        except ValueError:
                            disks[disk_id]['state'] = {'state': 'error',
                                                       'detail': 'corruption'}
                    else:
                        disks[disk_id]['state'] = {'state': 'error',
                                                   'detail': 'servicefailure'}
                    if disks[disk_id]['state']['state'] != 'error':
                        service_state = check_output('status {0}{1} || true'.format(API.SERVICE_PREFIX, asd_id), shell=True)
                        if 'start/running' not in service_state:
                            disks[disk_id]['state'] = {'state': 'error',
                                                       'detail': 'servicefailure'}
            disks[disk_id]['name'] = disk_id
            disks[disk_id]['node_id'] = API.NODE_ID
            API._disk_hateoas(disks[disk_id], disk_id)
        print '{0} - Fetching disks completed'.format(datetime.datetime.now())
        return disks

    @staticmethod
    @get('/disks')
    def list_disks():
        """ List all disk information """
        print '{0} - Listing disks'.format(datetime.datetime.now())
        data = API._list_disks()
        data['_parent'] = '/'
        data['_actions'] = []
        return data

    @staticmethod
    @get('/disks/<disk>')
    def index_disk(disk):
        """
        Retrieve information about a single disk
        :param disk: Guid of the disk
        """
        print '{0} - Listing disk {1}'.format(datetime.datetime.now(), disk)
        all_disks = API._list_disks()
        if disk not in all_disks:
            raise BadRequest('Disk unknown')
        data = all_disks[disk]
        API._disk_hateoas(data, disk)
        data['_link'] = '/disks/{0}'.format(disk)
        return data

    @staticmethod
    @post('/disks/<disk>/add')
    def add_disk(disk):
        """
        Add a disk
        :param disk: Guid of the disk
        """
        print '{0} - Add disk {1}'.format(datetime.datetime.now(), disk)
        with FileMutex('add_disk'), FileMutex('disk_'.format(disk)):
            print '{0} - Got lock for add disk {1}'.format(datetime.datetime.now(), disk)
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is False:
                raise BadRequest('Disk already configured')

            # Partitioning and mounting
            print '{0} - Preparing disk {1}'.format(datetime.datetime.now(), disk)
            asd_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
            Disks.prepare_disk(disk, asd_id)

            # Prepare & start service
            print '{0} - Setting up service for disk {1}'.format(datetime.datetime.now(), disk)
            port = EtcdConfiguration.get('{0}/main|port'.format(API.CONFIG_ROOT.format(API.NODE_ID)))
            ips = EtcdConfiguration.get('{0}/main|ips'.format(API.CONFIG_ROOT.format(API.NODE_ID)))
            used_ports = [all_disks[_disk]['port'] for _disk in all_disks
                          if all_disks[_disk]['available'] is False and 'port' in all_disks[_disk]]
            while port in used_ports:
                port += 1
            asd_config = {'home': '/mnt/alba-asd/{0}'.format(asd_id),
                          'node_id': API.NODE_ID,
                          'asd_id': asd_id,
                          'log_level': 'info',
                          'port': port}

            if EtcdConfiguration.exists('{0}/extra'.format(API.CONFIG_ROOT.format(API.NODE_ID))):
                data = EtcdConfiguration.get('{0}/extra'.format(API.CONFIG_ROOT.format(API.NODE_ID)))
                for extrakey in data:
                    asd_config[extrakey] = data[extrakey]

            if ips is not None and len(ips) > 0:
                asd_config['ips'] = ips
            EtcdConfiguration.set(API.ASD_CONFIG_ROOT.format(asd_id), json.dumps(asd_config), raw=True)
            with open('/opt/alba-asdmanager/config/upstart/alba-asd.conf', 'r') as template:
                contents = template.read()
            service_name = '{0}{1}'.format(API.SERVICE_PREFIX, asd_id)
            contents = contents.replace('<ASD>', asd_id)
            contents = contents.replace('<SERVICE_NAME>', service_name)
            with open('/etc/init/{0}.conf'.format(service_name), 'w') as upstart:
                upstart.write(contents)
            check_output('start {0}'.format(service_name), shell=True)

            print '{0} - Returning info about added disk {1}'.format(datetime.datetime.now(), disk)
            all_disks = API._list_disks()
            data = all_disks[disk]
            API._disk_hateoas(data, disk)
            data['_link'] = '/disks/{0}'.format(disk)
            return data

    @staticmethod
    @post('/disks/<disk>/delete')
    def delete_disk(disk):
        """
        Delete a disk
        :param disk: Guid of the disk
        """
        print '{0} - Deleting disk {1}'.format(datetime.datetime.now(), disk)
        with FileMutex('disk_'.format(disk)):
            print '{0} - Got lock for deleting disk {1}'.format(datetime.datetime.now(), disk)
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')

            # Stop and remove service
            print '{0} - Removing services for disk {1}'.format(datetime.datetime.now(), disk)
            asd_id = all_disks[disk]['asd_id']
            service_name = '{0}{1}'.format(API.SERVICE_PREFIX, asd_id)
            check_output('stop {0} || true'.format(service_name), shell=True)
            if os.path.exists('/etc/init/{0}.conf'.format(service_name)):
                os.remove('/etc/init/{0}.conf'.format(service_name))

            # Cleanup & unmount disk
            print '{0} - Cleaning disk {1}'.format(datetime.datetime.now(), disk)
            Disks.clean_disk(disk, asd_id)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @post('/disks/<disk>/restart')
    def restart_disk(disk):
        """
        Restart a disk
        :param disk: Guid of the disk
        """
        print '{0} - Restarting disk {1}'.format(datetime.datetime.now(), disk)
        with FileMutex('disk_'.format(disk)):
            print '{0} - Got lock for restarting disk {1}'.format(datetime.datetime.now(), disk)
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')

            # Stop service, remount, start service
            asd_id = all_disks[disk]['asd_id']
            service_name = '{0}{1}'.format(API.SERVICE_PREFIX, asd_id)
            check_output('stop {0} || true'.format(service_name), shell=True)
            check_output('umount /mnt/alba-asd/{0} || true'.format(asd_id), shell=True)
            check_output('mount /mnt/alba-asd/{0} || true'.format(asd_id), shell=True)
            check_output('start {0} || true'.format(service_name), shell=True)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @get('/update')
    def update():
        """ Retrieve available update APIs """
        return {'_link': '/update/information',
                '_actions': ['/update/execute',
                             '/update/restart_services']}

    @staticmethod
    def _get_sdm_services():
        services = {}
        for file_name in os.listdir('/etc/init/'):
            if file_name.startswith(API.SERVICE_PREFIX) and file_name.endswith('.conf'):
                file_name = file_name.rstrip('.conf')
                file_path = '/opt/alba-asdmanager/run/{0}.version'.format(file_name)
                if os.path.isfile(file_path):
                    with open(file_path) as fp:
                        services[file_name] = fp.read().strip()
        return services

    @staticmethod
    def _get_package_information(package_name):
        installed = None
        candidate = None
        for line in check_output('apt-cache policy {0} {1}'.format(package_name, API.APT_CONFIG_STRING), shell=True).splitlines():
            line = line.strip()
            if line.startswith('Installed:'):
                installed = line.lstrip('Installed:').strip()
            elif line.startswith('Candidate:'):
                candidate = line.lstrip('Candidate:').strip()

            if installed is not None and candidate is not None:
                break
        print '{0} - Installed version for package {1}: {2}'.format(datetime.datetime.now(), package_name, installed)
        print '{0} - Candidate version for package {1}: {2}'.format(datetime.datetime.now(), package_name, candidate)
        return installed, candidate

    @staticmethod
    def _update_packages():
        counter = 0
        max_counter = 3
        while True and counter < max_counter:
            counter += 1
            try:
                check_output('apt-get update {0}'.format(API.APT_CONFIG_STRING), shell=True)
                break
            except CalledProcessError as cpe:
                time.sleep(3)
                if counter == max_counter:
                    raise cpe
            except Exception as ex:
                raise ex

    @staticmethod
    @get('/update/information')
    def get_update_information():
        """ Retrieve update information """
        with FileMutex('package_update'):
            print '{0} - Locking in place for apt-get update'.format(datetime.datetime.now())
            API._update_packages()
            sdm_package_info = API._get_package_information(package_name=API.PACKAGE_NAME)
            sdm_installed = sdm_package_info[0]
            sdm_candidate = sdm_package_info[1]
            if sdm_installed != sdm_candidate:
                return {'version': sdm_candidate,
                        'installed': sdm_installed}

            alba_package_info = API._get_package_information(package_name='alba')
            services = [key for key, value in API._get_sdm_services().iteritems() if value != alba_package_info[1]]
            return {'version': sdm_candidate if services else '',
                    'installed': sdm_installed}

    @staticmethod
    @post('/update/execute/<status>')
    def execute_update(status):
        """
        Execute an update
        :param status: Current status of the update
        """
        with FileMutex('package_update'):
            try:
                API._update_packages()
                sdm_package_info = API._get_package_information(package_name=API.PACKAGE_NAME)
            except CalledProcessError:
                return {'status': 'started'}

            if sdm_package_info[0] != sdm_package_info[1]:
                if status == 'started':
                    print '{0} - Updating package {1}'.format(datetime.datetime.now(), API.PACKAGE_NAME)
                    check_output('echo "python {0} >> /var/log/ovs-upgrade-sdm.log 2>&1" > /tmp/update'.format(API.INSTALL_SCRIPT), shell=True)
                    check_output('at -f /tmp/update now', shell=True)
                    check_output('rm /tmp/update', shell=True)
                return {'status': 'running'}
            else:
                return {'status': 'done' if 'running' in check_output('status alba-asdmanager', shell=True).strip() else 'running'}

    @staticmethod
    @post('/update/restart_services')
    def restart_services():
        """ Restart services """
        with FileMutex('package_update'):
            API._update_packages()
            alba_package_info = API._get_package_information(package_name='alba')
            result = {}
            for service, running_version in API._get_sdm_services().iteritems():
                if running_version != alba_package_info[1]:
                    status = check_output('status {0}'.format(service), shell=True).strip()
                    if 'stop/waiting' in status:
                        print "{0} - Found stopped service {1}. Will not start it.".format(datetime.datetime.now(), service)
                        result[service] = 'stopped'
                    else:
                        print '{0} - Restarting service {1}'.format(datetime.datetime.now(), service)
                        try:
                            print '{0} - {1}'.format(datetime.datetime.now(), check_output('restart {0}'.format(service), shell=True))
                            result[service] = 'restarted'
                        except CalledProcessError as cpe:
                            print "{0} - Failed to restart service {1} {2}".format(datetime.datetime.now(), service, cpe)
                            result[service] = 'failed'

            return {'result': result}
