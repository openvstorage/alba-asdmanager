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
from source.tools.localclient import LocalClient
from source.tools.services.service import ServiceManager
from source.tools.packages.package import PackageManager
from subprocess import check_output
from subprocess import CalledProcessError

local_client = LocalClient()


class API(object):
    """ ALBA API """
    PACKAGE_NAME = 'openvstorage-sdm'
    ASD_SERVICE_PREFIX = 'alba-asd-'
    MAINTENANCE_PREFIX = 'ovs-alba-maintenance'
    INSTALL_SCRIPT = '/opt/asd-manager/source/tools/install/upgrade-package.py'
    ASD_CONFIG_ROOT = '/ovs/alba/asds/{0}'
    ASD_CONFIG = '/ovs/alba/asds/{0}/config'
    NODE_ID = os.environ['ASD_NODE_ID']
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)

    @staticmethod
    @get('/')
    def index():
        """ Return available API calls """
        return {'node_id': API.NODE_ID,
                '_links': ['/disks', '/net', '/update', '/maintenance'],
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
        EtcdConfiguration.set('{0}/network|ips'.format(API.CONFIG_ROOT), json.loads(request.form['ips']))
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
                    disks[disk_id].update(EtcdConfiguration.get(API.ASD_CONFIG.format(asd_id)))
                    service_name = '{0}{1}'.format(API.ASD_SERVICE_PREFIX, asd_id)
                    service_state = ServiceManager.get_service_status(service_name, local_client)
                    if service_state is False:
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
            port = EtcdConfiguration.get('{0}/network|port'.format(API.CONFIG_ROOT))
            ips = EtcdConfiguration.get('{0}/network|ips'.format(API.CONFIG_ROOT))
            used_ports = [all_disks[_disk]['port'] for _disk in all_disks
                          if all_disks[_disk]['available'] is False and 'port' in all_disks[_disk]]
            while port in used_ports:
                port += 1
            asd_config = {'home': '/mnt/alba-asd/{0}'.format(asd_id),
                          'node_id': API.NODE_ID,
                          'asd_id': asd_id,
                          'log_level': 'info',
                          'port': port}

            if EtcdConfiguration.exists('{0}/extra'.format(API.CONFIG_ROOT)):
                data = EtcdConfiguration.get('{0}/extra'.format(API.CONFIG_ROOT))
                for extrakey in data:
                    asd_config[extrakey] = data[extrakey]

            if ips is not None and len(ips) > 0:
                asd_config['ips'] = ips
            EtcdConfiguration.set(API.ASD_CONFIG.format(asd_id), json.dumps(asd_config), raw=True)

            service_name = '{0}{1}'.format(API.ASD_SERVICE_PREFIX, asd_id)
            params = {'ASD': asd_id,
                      'SERVICE_NAME': service_name}
            ServiceManager.add_service('alba-asd', local_client, params, service_name)
            ServiceManager.start_service(service_name, local_client)

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
            service_name = '{0}{1}'.format(API.ASD_SERVICE_PREFIX, asd_id)
            ServiceManager.stop_service(service_name, local_client)
            ServiceManager.remove_service(service_name, local_client)
            EtcdConfiguration.delete(API.ASD_CONFIG_ROOT.format(asd_id), raw=True)

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
            service_name = '{0}{1}'.format(API.ASD_SERVICE_PREFIX, asd_id)
            ServiceManager.stop_service(service_name, local_client)
            check_output('umount /mnt/alba-asd/{0} || true'.format(asd_id), shell=True)
            check_output('mount /mnt/alba-asd/{0} || true'.format(asd_id), shell=True)
            ServiceManager.start_service(service_name, local_client)

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
        for file_name in ServiceManager.list_service_files(local_client):
            if file_name.startswith(API.ASD_SERVICE_PREFIX):
                file_path = '/opt/asd-manager/run/{0}.version'.format(file_name)
                if os.path.isfile(file_path):
                    with open(file_path) as fp:
                        services[file_name] = fp.read().strip()
        return services

    @staticmethod
    def _get_package_information(package_name):
        installed, candidate = PackageManager.get_installed_candidate_version(package_name, local_client)
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
                PackageManager.update(local_client)
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
            print '{0} - Locking in place for package update'.format(datetime.datetime.now())
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
                    check_output('echo "python {0} >> /var/log/upgrade-openvstorage-sdm.log 2>&1" > /tmp/update'.format(API.INSTALL_SCRIPT), shell=True)
                    check_output('at -f /tmp/update now', shell=True)
                    check_output('rm /tmp/update', shell=True)
                return {'status': 'running'}
            else:
                status = ServiceManager.get_service_status('asd-manager', local_client)
                return {'status': 'done' if status is True else 'running'}

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
                    status = ServiceManager.get_service_status(service, local_client)
                    if status is False:
                        print "{0} - Found stopped service {1}. Will not start it.".format(datetime.datetime.now(),
                                                                                           service)
                        result[service] = 'stopped'
                    else:
                        print '{0} - Restarting service {1}'.format(datetime.datetime.now(), service)
                        try:
                            status = ServiceManager.restart_service(service, local_client)
                            print '{0} - {1}'.format(datetime.datetime.now(), status)
                            result[service] = 'restarted'
                        except CalledProcessError as cpe:
                            print "{0} - Failed to restart service {1} {2}".format(datetime.datetime.now(), service,
                                                                                   cpe)
                            result[service] = 'failed'

            return {'result': result}

    @staticmethod
    def _list_maintenance_services():
        """
        Retrieve all configured maintenance service running on this node for each backend
        :return: dict
        """
        services = {}
        for file_name in ServiceManager.list_service_files(local_client):
            print file_name
            if file_name.startswith(API.MAINTENANCE_PREFIX):
                with open(ServiceManager._get_service_filename(file_name, local_client)) as fp:
                    services[file_name] = {'config': fp.read().strip(),
                                           '_link': '',
                                           '_actions': ['/maintenance/{0}/remove'.format(file_name)]}
        return services

    @staticmethod
    @get('/maintenance')
    def list_maintenance_services():
        """ List all maintenance information """
        print '{0} - Listing maintenance services'.format(datetime.datetime.now())
        data = API._list_maintenance_services()
        data['_parent'] = '/'
        data['_actions'] = []
        return data

    @staticmethod
    @post('/maintenance/<name>/add')
    def add_maintenance_service(name):
        """
        Add a maintenance service with a specific name
        :param name:
        :return: None
        """
        if ServiceManager.has_service(name, local_client):
            if not ServiceManager.is_enabled(name, local_client):
                ServiceManager.enable_service(name, local_client)
        else:
            config_location = '/ovs/alba/backends/{0}/maintenance/config'.format(request.form['alba_backend_guid'])
            alba_config = 'etcd://127.0.0.1:2379{0}'.format(config_location)
            params = {'ALBA_CONFIG': alba_config}
            EtcdConfiguration.set(config_location, json.dumps({
                'log_level': 'info',
                'albamgr_cfg_url': 'etcd://127.0.0.1:2379/ovs/arakoon/{0}/config'.format(request.form['abm_name'])
            }), raw=True)

            ServiceManager.add_service(name='alba-maintenance', client=local_client, params=params, target_name=name)
        ServiceManager.start_service(name, local_client)

    @staticmethod
    @post('/maintenance/<name>/remove')
    def remove_maintenance_service(name):
        """
        Remove a maintenance service with a specific name
        :param name:
        :return: None
        """
        if ServiceManager.has_service(name, local_client):
            ServiceManager.stop_service(name, local_client)
        ServiceManager.remove_service(name, local_client)
