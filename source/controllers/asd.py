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
import math
import random
import signal
import string
from source.dal.lists.asdlist import ASDList
from source.dal.objects.asd import ASD
from source.tools.configuration.configuration import Configuration
from source.tools.localclient import LocalClient
from source.tools.log_handler import LogHandler
from source.tools.services.service import ServiceManager


class ASDController(object):
    """
    ASD Controller class
    """
    NODE_ID = os.environ['ASD_NODE_ID']
    CONFIG_ROOT = '/ovs/alba/asdnodes/{0}/config'.format(NODE_ID)

    _local_client = LocalClient()
    _logger = LogHandler.get('asd-manager', name='asd')

    @staticmethod
    def create_asd(disk):
        """
        Creates and starts an ASD on a given disk
        :param disk: Disk on which to create an ASD
        :type disk: source.dal.objects.disk.Disk
        :return: None
        """
        if disk.state == 'MISSING':
            raise RuntimeError('Cannot create an ASD on missing disk {0}'.format(disk.name))

        # Fetch disk information
        disk_size = int(ASDController._local_client.run(['df', '-B', '1', '--output=size', disk.mountpoint], timeout=5).splitlines()[1])

        # Find out appropriate disk size
        asd_size = int(math.floor(disk_size / (len(disk.asds) + 1)))
        for asd in disk.asds:
            if asd.has_config:
                config = Configuration.get(asd.config_key)
                config['capacity'] = asd_size
                config['rocksdb_block_cache_size'] = int(asd_size / 1024 / 4)
                Configuration.set(asd.config_key, config)
                try:
                    ServiceManager.send_signal(asd.service_name, signal.SIGUSR1, ASDController._local_client)
                except Exception as ex:
                    ASDController._logger.info('Could not send signal to ASD for reloading the quota: {0}'.format(ex))

        used_ports = []
        for asd in ASDList.get_asds():
            if asd.has_config:
                config = Configuration.get(asd.config_key)
                used_ports.append(config['port'])
                if 'rora_port' in config:
                    used_ports.append(config['rora_port'])

        # Prepare & start service
        asd_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        ASDController._logger.info('Setting up service for disk {0}'.format(disk.name))
        homedir = '{0}/{1}'.format(disk.mountpoint, asd_id)
        base_port = Configuration.get('{0}/network|port'.format(ASDController.CONFIG_ROOT))
        ips = Configuration.get('{0}/network|ips'.format(ASDController.CONFIG_ROOT))
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

        asd = ASD()
        asd.port = asd_port
        asd.hosts = asd_config.get('ips', [])
        asd.asd_id = asd_id
        asd.folder = asd_id
        asd.disk = disk
        asd.save()

        Configuration.set(asd.config_key, asd_config)
        params = {'CONFIG_PATH': Configuration.get_configuration_path(asd.config_key),
                  'SERVICE_NAME': asd.service_name,
                  'LOG_SINK': LogHandler.get_sink_path('alba_asd')}
        os.mkdir(homedir)
        ASDController._local_client.run(['chown', '-R', 'alba:alba', homedir])
        ServiceManager.add_service('alba-asd', ASDController._local_client, params, asd.service_name)
        ASDController.start_asd(asd)

    @staticmethod
    def remove_asd(asd):
        """
        Removes an ASD
        :param asd: ASD to remove
        :type asd: source.dal.objects.asd.ASD
        :return: None
        """
        if ServiceManager.has_service(asd.service_name, ASDController._local_client):
            ServiceManager.stop_service(asd.service_name, ASDController._local_client)
            ServiceManager.remove_service(asd.service_name, ASDController._local_client)
        try:
            ASDController._local_client.dir_delete('{0}/{1}'.format(asd.disk.mountpoint, asd.asd_id))
        except Exception as ex:
            ASDController._logger.warning('Could not clean ASD data: {0}'.format(ex))
        Configuration.delete(asd.config_key)
        asd.delete()

    @staticmethod
    def start_asd(asd):
        """
        Starts an ASD
        :param asd: ASD to start
        :type asd: source.dal.objects.asd.ASD
        :return: None
        """
        if ServiceManager.has_service(asd.service_name, ASDController._local_client):
            ServiceManager.start_service(asd.service_name, ASDController._local_client)

    @staticmethod
    def stop_asd(asd):
        """
        Stops an ASD
        :param asd: ASD to stop
        :type asd: source.dal.objects.asd.ASD
        :return: None
        """
        if ServiceManager.has_service(asd.service_name, ASDController._local_client):
            ServiceManager.stop_service(asd.service_name, ASDController._local_client)

    @staticmethod
    def restart_asd(asd):
        """
        Restart an ASD
        :param asd: ASD to remove
        :type asd: source.dal.objects.asd.ASD
        :return: None
        """
        if ServiceManager.has_service(asd.service_name, ASDController._local_client):
            ServiceManager.restart_service(asd.service_name, ASDController._local_client)

    @staticmethod
    def list_asd_services():
        """
        Retrieve all ASD services
        :return: generator
        """
        for service_name in ServiceManager.list_services(ASDController._local_client):
            if service_name.startswith(ASD.ASD_SERVICE_PREFIX.format('')):
                yield service_name
