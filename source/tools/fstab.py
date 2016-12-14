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
FSTAB related code
"""


class FSTab(object):
    """
    Class to modify the /etc/fstab file
    """
    _entry = '{0}  {1}  xfs  defaults,nofail,noatime,discard  0  2'
    _file_name = '/etc/fstab'
    _separators = ('# BEGIN ALBA ASDs', '# END ALBA ASDs')  # Don't change, for backwards compatibility

    @staticmethod
    def add(partition_aliases, mountpoint):
        """
        Add an entry for 1 of the partition_aliases if none present yet
        :param partition_aliases: Aliases of the partition to add to fstab
        :type partition_aliases: list
        :param mountpoint: Mountpoint on which the ASD is mounted
        :type mountpoint: str
        :return: None
        """
        if len(partition_aliases) == 0:
            raise ValueError('No aliases provided for partition')

        lines = FSTab._read()
        found = False
        for line in lines:
            for alias in partition_aliases:
                if line.startswith(alias):
                    found = True
                    break
            if found is True:
                break
        if found is False:
            lines.append(FSTab._entry.format(partition_aliases[0], mountpoint))
            FSTab._write(lines)

    @staticmethod
    def remove(partition_aliases):
        """
        Remove an entry for each alias in partition_aliases that's present in fstab
        :param partition_aliases: Aliases of the partition to remove from fstab
        :type partition_aliases: list
        :return: None
        """
        lines = FSTab._read()
        mounted_asds = len(lines)
        for line in list(lines):
            for partition_alias in partition_aliases:
                if partition_alias in line:
                    lines.remove(line)
        if mounted_asds != len(lines):
            FSTab._write(lines)

    @staticmethod
    def read():
        """
        Retrieve the mounted ASD information from fstab
        :return: Information about mounted ASDs (alias / mountpoint)
        :rtype: dict
        """
        lines = FSTab._read()
        disks = {}
        for line in lines:
            device, mountpoint = line.split()[:2]
            disks[device] = mountpoint
        return disks

    @staticmethod
    def _read():
        with open(FSTab._file_name, 'r') as fstab:
            contents = fstab.readlines()
        skip = True
        lines = []
        for line in contents:
            line = line.strip()
            if line.startswith(FSTab._separators[1]):
                break
            if skip is False:
                lines.append(line)
            if line.startswith(FSTab._separators[0]):
                skip = False
        return lines

    @staticmethod
    def _write(lines):
        with open(FSTab._file_name, 'r') as fstab:
            contents = fstab.readlines()
        skip = False
        new_content = []
        for line in contents:
            line = line.strip()
            if line.startswith(FSTab._separators[0]):
                skip = True
            if skip is False and line != '':
                new_content.append(line)
            if line.startswith(FSTab._separators[1]):
                skip = False
        if len(lines) > 0:
            new_content.append('')
            new_content.append(FSTab._separators[0])
            new_content.extend([line.strip() for line in lines])
            new_content.append(FSTab._separators[1])
        with open(FSTab._file_name, 'w') as fstab:
            fstab.write('{0}\n'.format('\n'.join(new_content)))
