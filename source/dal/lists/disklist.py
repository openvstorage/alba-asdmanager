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
BrandingList module
"""
from source.dal.datalist import DataList
from source.dal.objects.disk import Disk


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
    def get_by_name(name):
        """
        Returns a list of all Disks with a given name (including alias)
        """
        return DataList.query(Disk,
                              "SELECT id FROM {table} WHERE name=:name OR aliases LIKE :alias",
                              {'name': name,
                               'alias': '%"{0}"%'.format(name)})

    @staticmethod
    def contains_name(name):
        """
        Returns a list of all Disks that contains the given name, or has the given name as (part of) an alias
        """
        return DataList.query(Disk,
                              "SELECT id FROM {table} WHERE name LIKE :name OR aliases LIKE :name",
                              {'name': '%{0}%'.format(name)})
