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
This module contains the asd controller (logic for managing asds)
"""
import os
import json
import math
import random
import signal
import string
from source.tools.configuration.configuration import Configuration
from source.tools.fstab import FSTab
from source.tools.localclient import LocalClient
from source.tools.log_handler import LogHandler
from source.tools.services.service import ServiceManager


class ASDController(object):
    """
    ASD Controller class
    """
    NODE_ID = os.environ['ASD_NODE_ID']
    ASD_SERVICE_PREFIX = 'alba-asd-{0}'
    ASD_CONFIG_ROOT = '/ovs/alba/asds/{0}'
    ASD_CONFIG = '/ovs/alba/asds/{0}/config'
    ASDS = {}
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)

    _local_client = LocalClient()
    _logger = LogHandler.get('asd-manager', name='asd')

    @staticmethod
    def list_asds(mountpoint):
        """
        Lists all ASDs found on a given mountpoint
        :param mountpoint: Mountpoint to list ASDs on
        :type mountpoint: str
        :return: Dictionary of ASDs
        :rtype: dict
        """
        asds = {}
        try:
            for asd_id in os.listdir(mountpoint):
                if os.path.isdir('/'.join([mountpoint, asd_id])) and Configuration.exists(ASDController.ASD_CONFIG.format(asd_id)):
                    asds[asd_id] = Configuration.get(ASDController.ASD_CONFIG.format(asd_id))
                    output, error = ASDController._local_client.run(['ls', '{0}/{1}/'.format(mountpoint, asd_id)], allow_nonzero=True, return_stderr=True)
                    output += error
                    if 'Input/output error' in output:
                        asds[asd_id].update({'state': 'error',
                                             'state_detail': 'io_error'})
                        continue
                    service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
                    if ServiceManager.has_service(service_name, ASDController._local_client):
                        if ServiceManager.get_service_status(service_name, ASDController._local_client)[0] is False:
                            asds[asd_id].update({'state': 'error',
                                                 'state_detail': 'service_failure'})
                        else:
                            asds[asd_id].update({'state': 'ok'})
                    else:
                        asds[asd_id].update({'state': 'error',
                                             'state_detail': 'service_failure'})
        except OSError as ex:
            ASDController._logger.info('Error collecting ASD information: {0}'.format(str(ex)))
        return asds

    @staticmethod
    def create_asd(partition_alias):
        """
        Creates and starts an ASD on a given disk
        :param partition_alias: Alias of the partition of a disk  (eg: /dev/disk/by-id/scsi-1ATA_TOSHIBA_MK2002TSKB_92M1KDMHF-part1)
        :type partition_alias: str
        :return: None
        """
        all_asds = {}
        mountpoint = None
        for alias, mtpt in FSTab.read().iteritems():
            all_asds.update(ASDController.list_asds(mtpt))
            if alias == partition_alias:
                mountpoint = mtpt
        if mountpoint is None:
            raise RuntimeError('Failed to retrieve the mountpoint for partition with alias: {0}'.format(partition_alias))

        # Fetch disk information
        disk_size = int(ASDController._local_client.run(['df', '-B', '1', '--output=size', mountpoint], timeout=5).splitlines()[1])

        # Find out appropriate disk size
        asds = 1.0
        for asd_id in os.listdir(mountpoint):
            if os.path.isdir('/'.join([mountpoint, asd_id])) and Configuration.exists(ASDController.ASD_CONFIG.format(asd_id)):
                asds += 1
        asd_size = int(math.floor(disk_size / asds))
        for asd_id in os.listdir(mountpoint):
            if os.path.isdir('/'.join([mountpoint, asd_id])) and Configuration.exists(ASDController.ASD_CONFIG.format(asd_id)):
                config = json.loads(Configuration.get(ASDController.ASD_CONFIG.format(asd_id), raw=True))
                config['capacity'] = asd_size
                config['rocksdb_block_cache_size'] = int(asd_size / 1024 / 4)
                Configuration.set(ASDController.ASD_CONFIG.format(asd_id), json.dumps(config, indent=4), raw=True)
                try:
                    ServiceManager.send_signal(ASDController.ASD_SERVICE_PREFIX.format(asd_id),
                                               signal.SIGUSR1,
                                               ASDController._local_client)
                except Exception as ex:
                    ASDController._logger.info('Could not send signal to ASD for reloading the quota: {0}'.format(ex))

        # Prepare & start service
        asd_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        ASDController._logger.info('Setting up service for disk {0}'.format(partition_alias))
        homedir = '{0}/{1}'.format(mountpoint, asd_id)
        base_port = Configuration.get('{0}/network|port'.format(ASDController.CONFIG_ROOT))
        ips = Configuration.get('{0}/network|ips'.format(ASDController.CONFIG_ROOT))
        used_ports = []
        for asd in all_asds.itervalues():
            used_ports.append(asd['port'])
            if 'rora_port' in asd:
                used_ports.append(asd['rora_port'])
        asd_port = base_port
        rora_port = base_port + 1
        while asd_port in used_ports:
            asd_port += 1
        used_ports.append(asd_port)
        while rora_port in used_ports:
            rora_port += 1

        asd_config = {'home': homedir,
                      'node_id': ASDController.NODE_ID,
                      'asd_id': asd_id,
                      'capacity': asd_size,
                      'log_level': 'info',
                      'port': asd_port,
                      'transport': 'tcp',
                      'rocksdb_block_cache_size': int(asd_size / 1024 / 4)}
        if Configuration.get('/ovs/framework/rdma'):
            asd_config['rora_port'] = rora_port
            asd_config['rora_transport'] = 'rdma'
        if ips is not None and len(ips) > 0:
            asd_config['ips'] = ips

        if Configuration.exists('{0}/extra'.format(ASDController.CONFIG_ROOT)):
            data = Configuration.get('{0}/extra'.format(ASDController.CONFIG_ROOT))
            asd_config.update(data)

        Configuration.set(ASDController.ASD_CONFIG.format(asd_id), json.dumps(asd_config, indent=4), raw=True)

        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        params = {'CONFIG_PATH': Configuration.get_configuration_path('/ovs/alba/asds/{0}/config'.format(asd_id)),
                  'SERVICE_NAME': service_name,
                  'LOG_SINK': LogHandler.get_sink_path('alba_asd')}
        os.mkdir(homedir)
        ASDController._local_client.run(['chown', '-R', 'alba:alba', homedir])
        ServiceManager.add_service('alba-asd', ASDController._local_client, params, service_name)
        ASDController.start_asd(asd_id)

    @staticmethod
    def remove_asd(asd_id, mountpoint):
        """
        Removes an ASD
        :param asd_id: ASD identifier
        :type asd_id: str
        :param mountpoint: Mountpoint of the ASDs disk
        :type mountpoint: str
        :return: None
        """
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.stop_service(service_name, ASDController._local_client)
            ServiceManager.remove_service(service_name, ASDController._local_client)
        try:
            ASDController._local_client.dir_delete('{0}/{1}'.format(mountpoint, asd_id))
        except Exception as ex:
            ASDController._logger.warning('Could not clean ASD data: {0}'.format(ex))
        Configuration.delete(ASDController.ASD_CONFIG_ROOT.format(asd_id), raw=True)

    @staticmethod
    def start_asd(asd_id):
        """
        Starts an ASD
        :param asd_id: ASD identifier
        :type asd_id: str
        :return: None
        """
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.start_service(service_name, ASDController._local_client)

    @staticmethod
    def stop_asd(asd_id):
        """
        Stops an ASD
        :param asd_id: ASD identifier
        :type asd_id: str
        :return: None
        """
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.stop_service(service_name, ASDController._local_client)

    @staticmethod
    def restart_asd(asd_id):
        """
        Restart an ASD
        :param asd_id: ASD identifier
        :type asd_id: str
        :return: None
        """
        service_name = ASDController.ASD_SERVICE_PREFIX.format(asd_id)
        if ServiceManager.has_service(service_name, ASDController._local_client):
            ServiceManager.restart_service(service_name, ASDController._local_client)

    @staticmethod
    def list_asd_services():
        """
        Retrieve all ASD services
        :return: generator
        """
        for service_name in ServiceManager.list_services(ASDController._local_client):
            if service_name.startswith(ASDController.ASD_SERVICE_PREFIX.format('')):
                yield service_name
