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
SettingList module
"""

from ovs_extensions.dal.datalist import DataList
from source.dal.objects.setting import Setting


# noinspection SqlNoDataSourceInspection,SqlDialectInspection
class SettingList(object):
    """
    This SettingList class contains various lists regarding to the Setting class
    """

    @staticmethod
    def get_settings():
        """
        Returns a list of all Settings
        """
        return DataList.query(object_type=Setting, query='SELECT id FROM {table}')

    @staticmethod
    def get_setting_by_code(code):
        """
        Returns the setting based on the code passed
        """
        settings = DataList.query(object_type=Setting, query='SELECT id FROM {table} WHERE code=:code', parameters={'code': code})
        if len(settings) == 0:
            return
        return settings[0]
