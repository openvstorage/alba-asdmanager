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
ASDList module
"""
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.dal.datalist import DataList
from source.dal.objects.asd import ASD


# noinspection SqlNoDataSourceInspection
class ASDList(object):
    """
    This ASDList class contains various lists regarding to the ASD class
    """

    @staticmethod
    def get_asds():
        """
        Returns a list of all ASDs
        """
        return DataList.query(ASD, "SELECT id FROM {table}")

    @staticmethod
    def get_by_asd_id(asd_id):
        """
        Returns an ASD with the given ASD ID
        :param asd_id:
        :return:
        """
        asds = DataList.query(object_type=ASD, query="SELECT id FROM {table} WHERE asd_id=:asd_id", parameters={'asd_id': asd_id})
        if len(asds) > 1:
            raise ValueError('Multiple ASDs found with ASD ID {0}'.format(asd_id))
        if len(asds) == 0:
            raise ObjectNotFoundException('ASD with ASD ID {0} not found'.format(asd_id))
        return asds[0]
