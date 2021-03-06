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
from ovs_extensions.generic.sshclient import SSHClient
from source.constants.asd import ASD_NODE_CONFIG_NETWORK_LOCATION, ASD_NODE_CONFIG_LOCATION
from source.dal.lists.asdlist import ASDList
from source.dal.lists.settinglist import SettingList
from source.dal.objects.asd import ASD
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.osfactory import OSFactory
from source.tools.packagefactory import PackageFactory
from source.tools.servicefactory import ServiceFactory


class ASDController(object):
    """
    ASD Controller class
    """
    ASD_PREFIX = 'alba-asd'
    _logger = Logger('controllers')
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _service_manager = ServiceFactory.get_manager()

    @staticmethod
    def calculate_rocksdb_cache_size(is_ssd):
        """
        Calculate the cache size for the RocksDB
        :param disk: disk on which the asd is running
        :type disk: source.dal.objects.disk.Disk
        :return: None or int
        """
        if is_ssd:  # No cache size is required to be specified for ASDs
            return None
        else:
            return 128 * 1024 * 1024  # 128 MiB

    @staticmethod
    def create_asd(disk):
        """
        Creates and starts an ASD on a given disk
        :param disk: Disk on which to create an ASD
        :type disk: source.dal.objects.disk.Disk
        :return: None
        :rtype: NoneType
        """
        # Validations
        if disk.state == 'MISSING':
            raise RuntimeError('Cannot create an ASD on missing disk {0}'.format(disk.name))

        _node_id = SettingList.get_setting_by_code(code='node_id').value
        ipaddresses = Configuration.get('{0}|ips'.format(ASD_NODE_CONFIG_NETWORK_LOCATION.format(_node_id)))
        if len(ipaddresses) == 0:
            ipaddresses = OSFactory.get_manager().get_ip_addresses(client=ASDController._local_client)
            if len(ipaddresses) == 0:
                raise RuntimeError('Could not find any IP on the local node')

        alba_pkg_name, alba_version_cmd = PackageFactory.get_package_and_version_cmd_for(component='alba')  # Call here, because this potentially raises error, which should happen before actually making changes

        # Fetch disk information
        disk_size = int(ASDController._local_client.run(['df', '-B', '1', '--output=size', disk.mountpoint], timeout=5).splitlines()[1])

        # Find out appropriate disk size
        asd_size = int(math.floor(disk_size / (len(disk.asds) + 1)))
        for asd in disk.asds:
            if asd.has_config:
                config = Configuration.get(asd.config_key)
                config['capacity'] = asd_size
                cache_size = ASDController.calculate_rocksdb_cache_size(is_ssd=disk.is_ssd)
                if cache_size:
                    config.update({'rocksdb_block_cache_size': cache_size})
                Configuration.set(asd.config_key, config)
                try:
                    ASDController._service_manager.send_signal(asd.service_name, signal.SIGUSR1, ASDController._local_client)
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
        ASDController._logger.info('Setting up service for disk {0}'.format(disk.name))
        asd_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        homedir = '{0}/{1}'.format(disk.mountpoint, asd_id)
        base_port = Configuration.get('{0}|port'.format(ASD_NODE_CONFIG_NETWORK_LOCATION.format(_node_id)))

        asd_port = base_port
        rora_port = base_port + 1
        while asd_port in used_ports:
            asd_port += 1
        used_ports.append(asd_port)
        while rora_port in used_ports:
            rora_port += 1

        asd_config = {'ips': ipaddresses,
                      'home': homedir,
                      'port': asd_port,
                      'asd_id': asd_id,
                      'node_id': _node_id,
                      'capacity': asd_size,
                      'multicast': None,
                      'transport': 'tcp',
                      'log_level': 'info'
                      }
        cache_size = ASDController.calculate_rocksdb_cache_size(is_ssd=disk.is_ssd)
        if cache_size:
            asd_config.update({'rocksdb_block_cache_size': cache_size})
        if Configuration.get('/ovs/framework/rdma'):
            asd_config['rora_port'] = rora_port
            asd_config['rora_transport'] = 'rdma'

        if Configuration.exists('{0}/extra'.format(ASD_NODE_CONFIG_LOCATION.format(_node_id))):
            data = Configuration.get('{0}/extra'.format(ASD_NODE_CONFIG_LOCATION.format(_node_id)))
            asd_config.update(data)

        asd = ASD()
        asd.disk = disk
        asd.port = asd_port
        asd.hosts = ipaddresses
        asd.asd_id = asd_id
        asd.folder = asd_id
        asd.save()

        Configuration.set(asd.config_key, asd_config)
        params = {'LOG_SINK': Logger.get_sink_path('alba-asd_{0}'.format(asd_id)),
                  'CONFIG_PATH': Configuration.get_configuration_path(asd.config_key),
                  'SERVICE_NAME': asd.service_name,
                  'ALBA_PKG_NAME': alba_pkg_name,
                  'ALBA_VERSION_CMD': alba_version_cmd}
        os.mkdir(homedir)
        ASDController._local_client.run(['chown', '-R', 'alba:alba', homedir])
        ASDController._service_manager.add_service(name=ASDController.ASD_PREFIX,
                                                   client=ASDController._local_client,
                                                   params=params,
                                                   target_name=asd.service_name)
        ASDController.start_asd(asd)

    @staticmethod
    def update_asd(asd, update_data):
        """
        Updates an ASD with the 'update_data' provided
        :param asd: ASD to update
        :type asd: source.dal.objects.asd.ASD
        :param update_data: Data to update
        :type update_data: dict
        :raises ValueError: - When ASD configuration key is not present
                            - When an unsupported key is passed in via 'update_data'
        :return: None
        :rtype: NoneType
        """
        key_map = {'ips': 'hosts'}
        if not Configuration.exists(asd.config_key):
            raise ValueError('Failed to the configuration at location {0}'.format(asd.config_key))

        config = Configuration.get(asd.config_key)
        for key, value in update_data.iteritems():
            if key not in key_map:  # Only updating IPs is supported for now
                raise ValueError('Unsupported property provided: {0}. Only IPs can be updated for now'.format(key))
            setattr(asd, key_map[key], value)
            config[key] = value
        asd.save()
        Configuration.set(key=asd.config_key, value=config)

    @staticmethod
    def remove_asd(asd):
        """
        Remove an ASD
        :param asd: ASD to remove
        :type asd: source.dal.objects.asd.ASD
        :return: None
        :rtype: NoneType
        """
        if ASDController._service_manager.has_service(asd.service_name, ASDController._local_client):
            ASDController._service_manager.stop_service(asd.service_name, ASDController._local_client)
            ASDController._service_manager.remove_service(asd.service_name, ASDController._local_client)
        try:
            ASDController._local_client.dir_delete('{0}/{1}'.format(asd.disk.mountpoint, asd.asd_id))
        except Exception:
            ASDController._logger.exception('Could not clean ASD data')
        Configuration.delete(asd.config_key)
        asd.delete()

    @staticmethod
    def start_asd(asd):
        """
        Start an ASD
        :param asd: ASD to start
        :type asd: source.dal.objects.asd.ASD
        :return: None
        :rtype: NoneType
        """
        if ASDController._service_manager.has_service(asd.service_name, ASDController._local_client):
            ASDController._service_manager.start_service(asd.service_name, ASDController._local_client)

    @staticmethod
    def stop_asd(asd):
        """
        Stop an ASD
        :param asd: ASD to stop
        :type asd: source.dal.objects.asd.ASD
        :return: None
        :rtype: NoneType
        """
        if ASDController._service_manager.has_service(asd.service_name, ASDController._local_client):
            ASDController._service_manager.stop_service(asd.service_name, ASDController._local_client)

    @staticmethod
    def restart_asd(asd):
        """
        Restart an ASD
        :param asd: ASD to restart
        :type asd: source.dal.objects.asd.ASD
        :return: None
        :rtype: NoneType
        """
        if ASDController._service_manager.has_service(asd.service_name, ASDController._local_client):
            ASDController._service_manager.restart_service(asd.service_name, ASDController._local_client)

    @staticmethod
    def list_asd_services():
        """
        Retrieve all ASD services
        :return: The ASD Services present on this ALBA Node
        :rtype: generator
        """
        for service_name in ASDController._service_manager.list_services(ASDController._local_client):
            if service_name.startswith(ASD.ASD_SERVICE_PREFIX.format('')):
                yield service_name
