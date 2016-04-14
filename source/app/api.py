# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
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
from source.tools.fstab import FSTab
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
    def _log(message):
        print '{0} - {1}'.format(str(datetime.datetime.now()), message)

    @staticmethod
    @get('/')
    def index():
        """ Return available API calls """
        return {'node_id': API.NODE_ID,
                '_links': ['/disks', '/asds', '/net', '/update', '/maintenance'],
                '_actions': []}

    @staticmethod
    @get('/net', authenticate=False)
    def net():
        """ Retrieve IP information """
        API._log('Loading network information')
        output = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True)
        my_ips = output.split('\n')
        return {'ips': [found_ip.strip() for found_ip in my_ips if found_ip.strip() != '127.0.0.1' and found_ip.strip() != ''],
                '_links': [],
                '_actions': ['/net']}

    @staticmethod
    @post('/net')
    def set_net():
        """ Set IP information """
        API._log('Setting network information')
        EtcdConfiguration.set('{0}/network|ips'.format(API.CONFIG_ROOT), json.loads(request.form['ips']))
        return {'_link': '/net'}

    @staticmethod
    def _disk_hateoas(disk, disk_id):
        disk['_link'] = '/disks/{0}'.format(disk_id)
        links = []
        if disk['available'] is False:
            links.append('/disks/{0}/asds'.format(disk_id))
            actions = ['/disks/{0}/delete'.format(disk_id),
                       '/disks/{0}/asds'.format(disk_id)]
            if disk['state']['state'] == 'error':
                actions.append('/disks/{0}/restart'.format(disk_id))
        else:
            actions = ['/disks/{0}/add'.format(disk_id)]
        disk['_links'] = links
        disk['_actions'] = actions

    @staticmethod
    def _list_disks():
        API._log('Fetching disks')
        disks = Disks.list_disks()
        for disk_id in disks:
            disks[disk_id]['name'] = disk_id
            disks[disk_id]['node_id'] = API.NODE_ID
            API._disk_hateoas(disks[disk_id], disk_id)
        API._log('Fetching disks completed')
        return disks

    @staticmethod
    @get('/disks')
    def list_disks():
        """ List all disk information """
        API._log('Listing disks')
        data = API._list_disks()
        data['_parent'] = '/'
        data['_actions'] = []
        return data

    @staticmethod
    @get('/disks/<disk>')
    def index_disk(disk):
        """
        Retrieve information about a single disk
        :param disk: Identifier of the disk
        """
        API._log('Listing disk {0}'.format(disk))
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
        :param disk: Identifier of the disk
        """
        API._log('Add disk {0}'.format(disk))
        with FileMutex('add_disk'), FileMutex('disk_'.format(disk)):
            API._log('Got lock for add disk {0}'.format(disk))
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is False:
                raise BadRequest('Disk already configured')

            # Partitioning and mounting
            API._log('Preparing disk {0}'.format(disk))
            Disks.prepare_disk(disk)

            API._log('Returning info about added disk {0}'.format(disk))
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
        :param disk: Identifier of the disk
        """
        API._log('Deleting disk {0}'.format(disk))
        with FileMutex('disk_'.format(disk)):
            API._log('Got lock for deleting disk {0}'.format(disk))
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')
            mountpoints = FSTab.read()
            if disk in mountpoints:
                mountpoint = mountpoints[disk]
                asds = API._list_asds_disk(disk, mountpoint)
                if len(asds) != 0:
                    raise BadRequest('There are still ASDs configured on disk {0}'.format(disk))

            # Cleanup & unmount disk
            API._log('Cleaning disk {0}'.format(disk))
            Disks.clean_disk(disk)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    @post('/disks/<disk>/restart')
    def restart_disk(disk):
        """
        Restart a disk
        :param disk: Identifier of the disk
        """
        API._log('Restarting disk {0}'.format(disk))
        with FileMutex('disk_'.format(disk)):
            API._log('Got lock for restarting disk {0}'.format(disk))
            all_disks = API._list_disks()
            if disk not in all_disks:
                raise BadRequest('Disk not available')
            if all_disks[disk]['available'] is True:
                raise BadRequest('Disk not yet configured')
            mountpoints = FSTab.read()
            if disk in mountpoints:
                mountpoint = mountpoints[disk]
                asds = API._list_asds_disk(disk, mountpoint)
                if len(asds) != 0:
                    raise BadRequest('There are still ASDs configured on disk {0}'.format(disk))

            # Remount the disk
            Disks.remount_disk(disk)

            return {'_link': '/disks/{0}'.format(disk)}

    @staticmethod
    def _asd_hateoas(asd, disk_id, asd_id):
        asd['_link'] = '/disks/{0}/asds/{1}'.format(disk_id, asd_id)
        asd['_actions'] = ['/disks/{0}/asds/{1}/delete'.format(disk_id, asd_id)]

    @staticmethod
    def _list_asds_disk(disk, mountpoint):
        """
        Lists all ASDs
        """
        asds = {}
        for asd_id in os.listdir(mountpoint):
            if os.path.isdir('/'.join([mountpoint, asd_id])) and EtcdConfiguration.exists(API.ASD_CONFIG.format(asd_id)):
                asds[asd_id] = EtcdConfiguration.get(API.ASD_CONFIG.format(asd_id))
                service_name = '{0}{1}'.format(API.ASD_SERVICE_PREFIX, asd_id)
                if ServiceManager.has_service(service_name, local_client):
                    service_state = ServiceManager.get_service_status(service_name, local_client)
                    if service_state is False:
                        asds[asd_id]['state'] = {'state': 'error',
                                                 'detail': 'servicefailure'}
                    else:
                        asds[asd_id]['state'] = {'state': 'ok'}
                else:
                    asds[asd_id]['state'] = {'state': 'error',
                                             'detail': 'servicefailure'}
                API._asd_hateoas(asds[asd_id], disk, asd_id)
        return asds

    @staticmethod
    @get('/asds')
    def list_asds():
        asds = {}
        mountpoints = FSTab.read()
        for disk, mountpoint in mountpoints.iteritems():
            asds.update(API._list_asds_disk(disk, mountpoint))
        asds['_parent'] = '/'
        asds['_actions'] = []
        return asds

    @staticmethod
    @get('/disks/<disk>/asds')
    def list_asds_disk(disk):
        """
        Lists all ASDs on a given disk
        :param disk: Identifier of the disk
        """
        mountpoints = FSTab.read()
        if disk not in mountpoints:
            raise BadRequest('Disk {0} is not yet initialized'.format(disk))
        mountpoint = mountpoints[disk]
        asds = API._list_asds_disk(disk, mountpoint)
        asds['_parent'] = '/disks/{0}'.format(disk)
        asds['_actions'] = []
        return asds

    @staticmethod
    @post('/disks/<disk>/asds')
    def add_asd_disk(disk):
        """
        Adds an ASD to a disk
        :param disk: Identifier of the disk
        """
        mountpoints = FSTab.read()
        if disk not in mountpoints:
            raise BadRequest('Disk {0} is not yet initialized'.format(disk))
        with FileMutex('add_asd'):
            asd_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
            all_asds = {}
            mountpoints = FSTab.read()
            for disk, mountpoint in mountpoints.iteritems():
                all_asds.update(API._list_asds_disk(disk, mountpoint))
            mountpoint = mountpoints[disk]

            # Prepare & start service
            API._log('Setting up service for disk {0}'.format(disk))
            homedir = '{0}/{1}'.format(mountpoint, asd_id)
            port = EtcdConfiguration.get('{0}/network|port'.format(API.CONFIG_ROOT))
            ips = EtcdConfiguration.get('{0}/network|ips'.format(API.CONFIG_ROOT))
            used_ports = [all_asds[asd]['port'] for asd in all_asds]
            while port in used_ports:
                port += 1
            asd_config = {'home': homedir,
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
            EtcdConfiguration.set(API.ASD_CONFIG.format(asd_id), json.dumps(asd_config, indent=4), raw=True)

            service_name = '{0}{1}'.format(API.ASD_SERVICE_PREFIX, asd_id)
            params = {'ASD': asd_id,
                      'SERVICE_NAME': service_name}
            os.mkdir(homedir)
            check_output('chown -R alba:alba {0}'.format(homedir), shell=True)
            ServiceManager.add_service('alba-asd', local_client, params, service_name)
            ServiceManager.start_service(service_name, local_client)

    @staticmethod
    @post('/disks/<disk>/asds/<asd_id>/delete')
    def asd_delete(disk, asd_id):
        """
        Deletes an ASD on a given Disk
        :param disk: Idientifier of the Disk
        :param asd_id: The ASD ID of the ASD to be removed
        """
        # Stop and remove service
        API._log('Removing services for disk {0}'.format(disk))
        mountpoints = FSTab.read()
        if disk not in mountpoints:
            raise BadRequest('Disk {0} is not yet initialized'.format(disk))
        all_asds = {}
        mountpoints = FSTab.read()
        for disk, mountpoint in mountpoints.iteritems():
            all_asds.update(API._list_asds_disk(disk, mountpoint))
        if asd_id not in all_asds:
            raise BadRequest('Could not find ASD {0} on disk {1}'.format(asd_id, disk))
        mountpoint = mountpoints[disk]
        service_name = '{0}{1}'.format(API.ASD_SERVICE_PREFIX, asd_id)
        if ServiceManager.has_service(service_name, local_client):
            ServiceManager.stop_service(service_name, local_client)
            ServiceManager.remove_service(service_name, local_client)
        check_output('rm -rf {0}/{1}'.format(mountpoint, asd_id), shell=True)
        EtcdConfiguration.delete(API.ASD_CONFIG_ROOT.format(asd_id), raw=True)

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
        API._log('Installed version for package {0}: {1}'.format(package_name, installed))
        API._log('Candidate version for package {0}: {1}'.format(package_name, candidate))
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
            API._log('Locking in place for package update')
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
                    API._log('Updating package {0}'.format(API.PACKAGE_NAME))
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
                        API._log('Found stopped service {0}. Will not start it.'.format(service))
                        result[service] = 'stopped'
                    else:
                        API._log('Restarting service {0}'.format(service))
                        try:
                            status = ServiceManager.restart_service(service, local_client)
                            API._log(status)
                            result[service] = 'restarted'
                        except CalledProcessError as cpe:
                            API._log('Failed to restart service {0} {1}'.format(service, cpe))
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
        API._log('Listing maintenance services')
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
            }, indent=4), raw=True)

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
