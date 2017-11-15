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
DiskList module
"""
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.dal.datalist import DataList
from source.dal.objects.disk import Disk


class DiskNotFoundError(RuntimeError):
    """
    Error raised when a disk is not found on the system
    """
    pass


# noinspection SqlNoDataSourceInspection
class DiskList(object):
    """
    This DiskList class contains various lists regarding to the Disk class
    """

    @staticmethod
    def get_disks():
        """
        Returns a list of all Disks
        """
        return DataList.query(Disk, "SELECT id FROM {table}")

    @staticmethod
    def get_usable_disks():
        """
        Returns a list of all disks that are "usable"
        """
        disks = []
        for disk in DiskList.get_disks():
            if disk.usable:
                disks.append(disk)
        return disks

    @staticmethod
    def get_by_alias(alias):
        """
        Gets a Disk by its alias.
        :param alias: Alias to search
        :type alias: str
        :return: The found Disk
        :rtype: source.dal.objects.disk.Disk
        """
        for disk in DiskList.get_usable_disks():
            for disk_alias in disk.aliases:
                if disk_alias.endswith(alias):
                    return disk
            partition_aliases = []
            for partition_info in disk.partitions:
                partition_aliases += partition_info['aliases']
            if alias in partition_aliases:
                return disk
        raise ObjectNotFoundException('Disk with alias {0} not available'.format(alias))
