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
This module contains the asd controller (logic for managing asds)
"""
import os
import json
import math
import random
import signal
import string
import datetime
from subprocess import check_output
from source.tools.configuration import EtcdConfiguration
from source.tools.fstab import FSTab
from source.tools.localclient import LocalClient
from source.tools.services.service import ServiceManager


class ASDController(object):
    NODE_ID = os.environ['ASD_NODE_ID']
    ASD_SERVICE_PREFIX = 'alba-asd-{0}'
    ASD_CONFIG_ROOT = '/ovs/alba/asds/{0}'
    ASD_CONFIG = '/ovs/alba/asds/{0}/config'
    ASDS = {}
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)

    _local_client = LocalClient()

    @staticmethod
    def _log(message):
        print '{0} - {1}'.format(str(datetime.datetime.now()), message)

    @staticmethod
    def list_asds(mountpoint):
        asds = {}
        try:
            for asd_id in os.listdir(mountpoint):
                if os.path.isdir('/'.join([mountpoint, asd_id])) and EtcdConfiguration.exists(ASDController.ASD_CONFIG.format(asd_id)):
                    asds[asd_id] = EtcdConfiguration.get(ASDController.ASD_CONFIG.format(asd_id))
                    output = check_output('ls {0}/{1}/ 2>&1 || true'.format(mountpoint, asd_id), shell=True)
                    if 'Input/output error' in output:
                        asds[asd_id].update({'state': 'error',
                                             'state_detail': 'ioerror'})
                        continue
                    service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
                    if ServiceManager.has_service(service_name, ASDController._local_client):
                        service_state = ServiceManager.get_service_status(service_name, ASDController._local_client)
                        if service_state is False:
                            asds[asd_id].update({'state': 'error',
                                                 'state_detail': 'servicefailure'})
                        else:
                            asds[asd_id].update({'state': 'ok'})
                    else:
                        asds[asd_id].update({'state': 'error',
                                             'state_detail': 'servicefailure'})
        except OSError as ex:
            ASDController._log('Error collecting ASD information: {0}'.format(str(ex)))
        return asds

    @staticmethod
    def create_asd(disk):
        all_asds = {}
        mountpoints = FSTab.read()
        for mountpoint in mountpoints.values():
            all_asds.update(ASDController.list_asds(mountpoint))
        mountpoint = mountpoints[disk]

        # Fetch disk information
        disk_size = int(check_output('df -B 1 --output=size {0} || true'.format(mountpoint), shell=True).splitlines()[1])

        # Find out appropriate disk size
        asds = 1.0
        for asd_id in os.listdir(mountpoint):
            if os.path.isdir('/'.join([mountpoint, asd_id])) and EtcdConfiguration.exists(ASDController.ASD_CONFIG.format(asd_id)):
                asds += 1
        asd_size = int(math.floor(disk_size / asds))
        for asd_id in os.listdir(mountpoint):
            if os.path.isdir('/'.join([mountpoint, asd_id])) and EtcdConfiguration.exists(ASDController.ASD_CONFIG.format(asd_id)):
                config = json.loads(EtcdConfiguration.get(ASDController.ASD_CONFIG.format(asd_id), raw=True))
                config['capacity'] = asd_size
                EtcdConfiguration.set(ASDController.ASD_CONFIG.format(asd_id), json.dumps(config, indent=4), raw=True)
                try:
                    ServiceManager.send_signal(ASDController.ASD_SERVICE_PREFIX.format(asd_id),
                                               signal.SIGUSR1,
                                               ASDController._local_client)
                except Exception as ex:
                    ASDController._log('Could not send signal to ASD for reloading the quota: {0}'.format(ex))

        # Prepare & start service
        asd_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        ASDController._log('Setting up service for disk {0}'.format(disk))
        homedir = '{0}/{1}'.format(mountpoint, asd_id)
        port = EtcdConfiguration.get('{0}/network|port'.format(ASDController.CONFIG_ROOT))
        ips = EtcdConfiguration.get('{0}/network|ips'.format(ASDController.CONFIG_ROOT))
        used_ports = [all_asds[asd]['port'] for asd in all_asds]
        while port in used_ports:
            port += 1
        asd_config = {'home': homedir,
                      'node_id': ASDController.NODE_ID,
                      'asd_id': asd_id,
                      'capacity': asd_size,
                      'log_level': 'info',
                      'port': port}

        if EtcdConfiguration.exists('{0}/extra'.format(ASDController.CONFIG_ROOT)):
            data = EtcdConfiguration.get('{0}/extra'.format(ASDController.CONFIG_ROOT))
            asd_config.update(data)

        if ips is not None and len(ips) > 0:
            asd_config['ips'] = ips
        EtcdConfiguration.set(ASDController.ASD_CONFIG.format(asd_id), json.dumps(asd_config, indent=4), raw=True)

        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        params = {'ASD': asd_id,
                  'SERVICE_NAME': service_name}
        os.mkdir(homedir)
        check_output('chown -R alba:alba {0}'.format(homedir), shell=True)
        ServiceManager.add_service('alba-asd', ASDController._local_client, params, service_name)
        ASDController.start_asd(asd_id)

    @staticmethod
    def remove_asd(asd_id, mountpoint):
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.stop_service(service_name, ASDController._local_client)
            ServiceManager.remove_service(service_name, ASDController._local_client)
        ASDController._local_client.dir_delete('{0}/{1}'.format(mountpoint, asd_id))
        EtcdConfiguration.delete(ASDController.ASD_CONFIG_ROOT.format(asd_id), raw=True)

    @staticmethod
    def start_asd(asd_id):
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.start_service(service_name, ASDController._local_client)

    @staticmethod
    def stop_asd(asd_id):
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.stop_service(service_name, ASDController._local_client)

    @staticmethod
    def restart_asd(asd_id):
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.restart_service(service_name, ASDController._local_client)
