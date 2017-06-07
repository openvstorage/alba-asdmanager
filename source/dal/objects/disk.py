# Copyright (C) 2017 iNuron NV
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
This is the Disk's module
"""

import os
from ovs_extensions.dal.structures import Property
from ovs_extensions.generic.sshclient import SSHClient
from source.dal.asdbase import ASDBase


class Disk(ASDBase):
    """
    Represents a disk on the system.
    """

    _local_client = SSHClient(endpoint='127.0.0.1', username='root')

    _table = 'disk'
    _properties = [Property(name='name', property_type=str, unique=True, mandatory=True),
                   Property(name='state', property_type=str, unique=False, mandatory=False),
                   Property(name='aliases', property_type=list, unique=True, mandatory=False),
                   Property(name='is_ssd', property_type=bool, unique=False, mandatory=False),
                   Property(name='model', property_type=str, unique=False, mandatory=False),
                   Property(name='size', property_type=int, unique=False, mandatory=True),
                   Property(name='serial', property_type=str, unique=True, mandatory=False),
                   Property(name='partitions', property_type=dict, unique=False, mandatory=False)]
    _relations = []
    _dynamics = ['mountpoint', 'available', 'usable', 'status', 'usage', 'partition_aliases']

    def _mountpoint(self):
        for partition in self.partitions:
            mountpoint = partition['mountpoint']
            if mountpoint is not None:
                return mountpoint
        return None

    def _available(self):
        return self.mountpoint is None or not self.mountpoint.startswith('/mnt/alba-asd/')

    def _usable(self):
        mountpoints = []
        for partition in self.partitions:
            mountpoint = partition['mountpoint']
            if mountpoint is not None:
                mountpoints.append(mountpoint)
        if len(mountpoints) > 1:
            return False  # Multiple mountpoints: Not supported
        if self.mountpoint is not None:
            # Only one mountpoint. Accept if it managed by us
            if not self.mountpoint.startswith('/mnt/alba-asd/'):
                return False
            return True
        # No mountpoint(s): Search for "forbidden" partition types
        for partition in self.partitions:
            partition_filesystem = partition['filesystem']
            if partition_filesystem in ['swap', 'linux_raid_member', 'LVM2_member']:
                return False
        return True

    def _status(self):
        if self.mountpoint is not None:
            if self.state == 'MISSING':
                return {'state': 'error',
                        'detail': 'missing'}
            output, error = self._local_client.run(['ls', '{0}/'.format(self.mountpoint)],
                                                   allow_nonzero=True, return_stderr=True, timeout=5)
            output += error
            if 'Input/output error' in output:
                return {'state': 'error',
                        'detail': 'io_error'}
        return {'state': 'ok'}

    def _usage(self):
        if self.mountpoint is not None:
            df_info = self._local_client.run("df -B 1 --output=size,used,avail '{0}' | tail -1 || true".format(self.mountpoint.replace(r"'", r"'\''")),
                                             allow_insecure=True, timeout=5).strip().splitlines()
            if len(df_info) == 1:
                size, used, available = df_info[0].split()
                return {'size': int(size),
                        'used': int(used),
                        'available': int(available)}
        return {}

    def _partition_aliases(self):
        partition_aliases = []
        for partition_info in self.partitions:
            partition_aliases += partition_info['aliases']
        return partition_aliases

    def export(self):
        """
        Exports this Disk's information to a dict structure
        :return: Representation of the Disk as dict
        :rtype: dict
        """
        return {'size': self.size,
                'usage': self.usage,
                'state': self.status['state'],
                'device': '/dev/{0}'.format(self.name),
                'aliases': self.aliases,
                'node_id': os.environ['ASD_NODE_ID'],
                'available': self.available,
                'mountpoint': self.mountpoint,
                'state_detail': self.status.get('detail', ''),
                'partition_amount': len(self.partitions),
                'partition_aliases': self.partition_aliases}
