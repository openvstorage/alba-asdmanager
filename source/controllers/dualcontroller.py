# Copyright (C) 2018 iNuron NV
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
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.generic.sshclient import SSHClient
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from source.controllers.asd import ASDController
from source.controllers.disk import DiskController
from source.dal.lists.asdlist import ASDList
from source.dal.lists.disklist import DiskList
from source.dal.lists.settinglist import SettingList
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.servicefactory import ServiceFactory
from source.tools.relationmanager import RelationManager


class DualController(object):
    """
    Class responsible for syncing models for Dual Controller support
    """
    _logger = Logger('controllers')
    _service_manager = ServiceFactory.get_manager()
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')

    OSD_DATA_FORMAT = {'folder': (str, None, True),
                       'home': (str, None, True),
                       'node_id': (str, None, False),
                       'asd_id': (str, None, True),
                       'port': (int, None, True),
                       'transport': (str, None, True)}
    SLOT_DATA_FORMAT = {'aliases': (list, str, True),
                        'mountpoint': (str, None, True),
                        'node_id': (str, None, True),
                        'osds': (dict, None, True),
                        'partition_aliases': (list, str, True)}

    @classmethod
    def sync_stack(cls, stack):
        """
        Synchronize a stack from an AlbaNode and mimic it's layout
        :param stack: Stack to sync with
        :type stack: dict
        :return: None
        :rtype: NoneType
        """
        stack = cls.filter_validate_stack(stack)
        # Compare the stack to our own
        # @Todo check for removals too
        # @todo figure out a way to check if fstab is falling behind on the passive side (outdated entries and such)
        for slot_id, slot_data in stack.iteritems():
            try:
                disk = DiskList.get_by_alias(slot_id)
                # Prepare the disk passively
                DiskController.prepare_disk(disk, slot_data)
                for osd_id, osd_data in slot_data['osds'].iteritems():
                    try:
                        asd = ASDList.get_by_asd_id(osd_id)
                    except ObjectNotFoundException:
                        # Create the ASD
                        cls._logger.info('Syncing stack - Disk with alias {0} is missing ASD {0}. Modelling it'.format(slot_id, osd_id))
                        # @todo create ASD
                        ASDController.create_asd(disk, asd_config=osd_data)
            except ObjectNotFoundException:
                # Disk is not part of this ASD Manager, nothing to do
                cls._logger.info('Syncing stack - Disk with alias {0} not found, syncing might be required. Skipping...'.format(slot_id))

    @classmethod
    def sync_fstab(cls):
        """
        Sync the FStab with the current stack layout
        :return: None
        :rtype: NoneType
        """
        pass

    @classmethod
    def _model_asd(cls, asd_data):
        """
        Models an ASD based on the provided data
        :param asd_data: Data to model the ASD from
        Example:
        {'folder': 'uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK',
        'home': '/mnt/alba-asd/zKjvJAePSLsJDFkB/uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK',
        'node_id': 'ApTUw7u66UOiGuW3',
        'osd_id': 'uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK',
        'port': 8602,
        'rocksdb_block_cache_size': 488139647,
        'transport': 'tcp',
        :type asd_data: dict
        :return: Newly modeled ASD
        """
        ExtensionsToolbox.verify_required_params(required_params=cls.OSD_DATA_FORMAT, actual_params=asd_data)

    @classmethod
    def filter_validate_stack(cls, stack):
        """
        Validates the stack data
        :param stack: Stack to validate (stack property of an AlbaNode)
        Example: {'ata-QEMU_HARDDISK_00e8797e-511c-11e7-9': {'aliases': ['/dev/disk/by-id/ata-QEMU_HARDDISK_00e8797e-511c-11e7-9', '/dev/disk/by-path/pci-0000:00:08.0-ata-2'],
                                                            'available': True,
                                                            'device': '/dev/sdc',
                                                            'mountpoint': None,
                                                            'node_id': 'te1paUNS8C6wgBzy',
                                                            'osds': {},
                                                            'partition_aliases': [],
                                                            'partition_amount': 0,
                                                            'size': 32212254720,
                                                            'status': 'empty',
                                                            'status_detail': '',
                                                            'usage': {}},
                 'ata-TOSHIBA_MK2002TSKB_6243KTUMF':        {'aliases': ['/dev/disk/by-id/ata-TOSHIBA_MK2002TSKB_6243KTUMF', '/dev/disk/by-id/wwn-0x500003941b800bab', '/dev/disk/by-path/pci-0000:00:1f.2-ata-6'],
                                                            'available': False,
                                                            'device': '/dev/sdf',
                                                            'mountpoint': '/mnt/alba-asd/zKjvJAePSLsJDFkB',
                                                            'node_id': 'ApTUw7u66UOiGuW3',
                                                            'osds': {'uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK': {'asd_id': 'uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK',
                                                                                                          'capacity': 1999419994112,
                                                                                                          'claimed_by': 'e2de6280-f25f-4749-a2d0-6682f6bd94b2',
                                                                                                          'folder': 'uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK',
                                                                                                          'home': '/mnt/alba-asd/zKjvJAePSLsJDFkB/uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK',
                                                                                                          'ips': ['10.100.189.31'],
                                                                                                          'log_level': 'info',
                                                                                                          'metadata': None,
                                                                                                          'multicast': None,
                                                                                                          'node_id': 'ApTUw7u66UOiGuW3',
                                                                                                          'osd_id': 'uYhK5xGQogKkRCqMTgHxtqW8dC0GRJPK',
                                                                                                          'port': 8602,
                                                                                                          'rocksdb_block_cache_size': 488139647,
                                                                                                          'status': 'ok',
                                                                                                          'status_detail': '',
                                                                                                          'transport': 'tcp',
                                                                                                          'type': 'ASD'}},
                                                            'partition_aliases': ['/dev/disk/by-id/ata-TOSHIBA_MK2002TSKB_6243KTUMF-part1', '/dev/disk/by-id/wwn-0x500003941b800bab-part1', '/dev/disk/by-partlabel/ata-TOSHIBA_MK2002TSKB_6243KTUMF','/dev/disk/by-path/pci-0000:00:1f.2-ata-6-part1'],
                                                            'partition_amount': 1,
                                                            'size': 2000398934016,
                                                            'status': 'ok',
                                                            'status_detail': '',
                                                            'usage': {'available': 1999306240000, 'size': 1999419994112, 'used': 113754112}}}}
        :type stack: dict
        :return: Filtered stack
        :rtype: dict
        """
        if not isinstance(stack, dict):
            raise ValueError('The stack should be a dict')
        filtered_stack = stack.copy()  # Shallow copy
        for slot_id, slot_data in stack.iteritems():
            if slot_data.get('osds', {}) == {}:
                filtered_stack.pop(slot_id)
                continue
            ExtensionsToolbox.verify_required_params(required_params=cls.SLOT_DATA_FORMAT, actual_params=slot_data)
            for osd_id, osd_data in slot_data['osds'].iteritems():
                ExtensionsToolbox.verify_required_params(required_params=cls.OSD_DATA_FORMAT, actual_params=osd_data)
        return filtered_stack

    @staticmethod
    def _diff(first, second):
        """
        Return the difference between both lists
        :param first: First list
        :param second: Second list
        :return: List of items that are different
        """
        try:
            # Try to reduce complexity from n^2 to O(n log n) due to removing potential duplicates
            second = set(second)
        except TypeError:
            pass
        return [item for item in first if item not in second]

    @classmethod
    def claim_ownership(cls, disk):
        """
        Claim ownership of all OSDs on the slot
        :param disk: Disk to claim ownership for
        :type disk: source.dal.objects.disk.Disk
        :return: None
        :rtype: NoneType
        """
        errors = []
        if not RelationManager.is_part_of_cluster():
            raise ValueError('Not part of a node cluster. No ownership changes can be made')
        node_id = SettingList.get_setting_by_code(code='node_id').value
        for asd in disk.asds:
            if not cls._service_manager.has_service(asd.service_name, cls._local_client):
                errors.append('No service found for ASD {0}'.format(asd.asd_id))
                continue
            if not Configuration.exists(asd.config_key):
                errors.append('No configuration entry for ASD {0}'.format(asd.asd_id))
        if len(errors) > 0:
            raise RuntimeError('Ownership cannot be claimed for Disk {0}: \n - {1}'.format(disk.aliases[0], '\n - '.join(errors)))
        for asd in disk.asds:
            # Change to node id
            asd_config = Configuration.get(asd.config_key)
            asd_config['node_id'] = node_id
            Configuration.set(asd.config_key, asd_config)
            RelationManager.register_asd_usage(asd.asd_id)
            cls._service_manager.start_service(asd.service_name, cls._local_client)
