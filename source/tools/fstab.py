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
import operator
import os


class FSTab(object):
    """
    Class to modify the /etc/fstab file
    """
    _DEFAULT_FILESYSTEM = 'xfs'
    _DEFAULT_OPTIONS = 'defaults,noatime,discard'
    _DEFAULT_DUMP = 0
    _DEFAULT_PASS = 2
    _file_name = os.path.join(os.path.sep, 'etc', 'fstab')
    _separators = ('# BEGIN ALBA ASDs', '# END ALBA ASDs')  # Don't change, for backwards compatibility

    @classmethod
    def add(cls, partition_aliases, mountpoint, no_fail=True, no_auto=False):
        """
        Add an entry for 1 of the partition_aliases if none present yet
        :param partition_aliases: Aliases of the partition to add to fstab
        :type partition_aliases: list
        :param mountpoint: Mountpoint on which the ASD is mounted
        :type mountpoint: str
        :param no_fail: Enable the nofail option. (Do not report errors for this device if it does not exist)
        :type no_fail: bool
        :param no_auto: Avoid automatic mounting
        :type no_auto: bool
        :return: None
        """
        if len(partition_aliases) == 0:
            raise ValueError('No aliases provided for partition')
        entries = cls._read_asd_entries()
        found = len(list(cls._filter_entries([('device', partition_aliases)], eq=True))) > 0
        if found is True:
            # Nothing to add
            return
        options = []
        if no_fail is True:
            options.append('nofail')
        if no_auto is True:
            options.append('noauto')
        all_options = cls._DEFAULT_OPTIONS
        if len(options) > 0:
            all_options = '{0},{1}'.format(all_options, ','.join(options))
        new_entry = FSTabEntry(device=partition_aliases[0],
                               mountpoint=mountpoint,
                               filesystem=cls._DEFAULT_FILESYSTEM,
                               options=all_options,
                               d=cls._DEFAULT_DUMP,
                               p=cls._DEFAULT_PASS)
        entries.append(new_entry)
        FSTab._write_asd_entries(entries)

    @classmethod
    def remove(cls, partition_aliases=None, mountpoint=None):
        """
        Remove an entry for each alias in partition_aliases that's present in fstab
        :param partition_aliases: Aliases of the partition to remove from fstab
        :type partition_aliases: list
        :param mountpoint: Search entries by mountpoint to remove from fstab
        :type mountpoint: str
        :return: None
        """
        entries = cls._read_asd_entries()
        filter_options = [(attr, value) for attr, value in [('device', partition_aliases), ('mountpoint', mountpoint)] if value is not None]
        filtered_entries = list(cls._filter_entries(filter_options, entries))
        if entries != filtered_entries:
            FSTab._write_asd_entries(filtered_entries)

    @staticmethod
    def read():
        """
        Retrieve the mounted ASD information from fstab
        :return: Information about mounted ASDs (alias / mountpoint)
        :rtype: dict
        """
        entries = FSTab._read_asd_entries()
        return {entry.device: entry.mountpoint for entry in entries}

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

    @staticmethod
    def _hydrate_entry(line):
        """
        Parse and add a line from fstab
        :param line: line that is present in fstab
        :type line: str
        :return: Hydrated Entry instance
        :rtype: FSTABEntry
        """
        return FSTabEntry(*filter(lambda x: x not in ('', ' ', None), str(line).strip("\n").split(" ")))

    @classmethod
    def _read_fstab(cls, raw=False):
        """
        Read the whole FSTAB file and return the contents
        :param raw: Return the raw file contents (if False, it returns it as a list)
        :type raw: bool
        :return: Contents of the FSTAB file
        """
        with open(cls._file_name, 'r') as fstab:
            if raw is True:
                return fstab.read()
            return fstab.readlines()

    @classmethod
    def _read_asd_entries(cls):
        """
        Reads the FSTAB file
        :return: List of entries related to the ASD Manager
        :rtype: list[FSTabEntry]
        """
        contents = cls._read_fstab()
        asd_entries = []
        in_asd_section = False
        for line in contents:
            line = line.strip()
            if line.startswith(cls._separators[1]):  # No longer in ASD section
                break
            if line.startswith(FSTab._separators[0]):  # Started in ASD section
                in_asd_section = True
                continue
            if in_asd_section is True:
                asd_entries.append(cls._hydrate_entry(line))
        return asd_entries

    @classmethod
    def _write_asd_entries(cls, entries):
        """
        Write new ASD Entries
        :param entries: List of entries to write
        :type entries: list[FSTabEntry]
        :return: None
        """
        contents = cls._read_fstab()
        in_asd_section = False
        new_content = []
        for line in contents:
            line = line.strip()
            if line.startswith(FSTab._separators[0]):  # In ASD section
                in_asd_section = True
            if line.startswith(FSTab._separators[1]):  # No longer in ASD section
                in_asd_section = False
                continue
            if in_asd_section is False and line != '':  #
                new_content.append(line)
        if len(entries) > 0:
            new_content.append('')
            new_content.append(FSTab._separators[0])
            new_content.extend([str(entry) for entry in entries])
            new_content.append(FSTab._separators[1])
        with open(FSTab._file_name, 'w') as fstab:
            fstab.write('{0}\n'.format('\n'.join(new_content)))

    @classmethod
    def _filter_entries(cls, filter_options, entries=None, eq=False):
        """
        Filters the fetched list of ASD entries
        The filter behaves in a 'not-equal' way by default
        :param filter_options: List of filter options. A filter option is a tuple with (attribute as string, value)
        :type filter_options: list[tuple(str, any)]
        :param entries: List of entries
        :type entries: list[FSTabEntry]
        :param eq: Use equal to filter
        :type eq: bool
        :return: Filtered list of entries
        :rtype: list[FSTabEntry]
        """
        entries = entries or cls._read_asd_entries()
        for entry in entries:
            for attr, value in filter_options:
                if isinstance(value, list):
                    op = operator.contains
                else:
                    op = operator.eq
                attr_value = getattr(entry, attr)
                outcome = op(value, attr_value)
                if eq is False:
                    outcome = operator.not_(outcome)
                if outcome is True:
                    yield entry


class FSTabEntry(object):
    """
    Entry class represents a non-comment line on the `/etc/fstab` file
    """

    def __init__(self, device, mountpoint, filesystem, options, d=0, p=0):
        """
        Initializes a new FSTABEntry
        :param device: devicename eg /dev/sda
        :param mountpoint: point where the device is mounted eg /mnt/sda
        :param filesystem: type of filesystem eg ext4
        :param options: extra options eg 'defaults'
        :param d: Dump option: filesystems needs to be dumped or not when the system goes down. Binary value
        :param p: Pass option: order to check filesystem at reboot time.
        Options: 0: skip checking, 1: Reserved for root filesystem. Any other number can be used
        """
        self.device = device
        self.mountpoint = mountpoint
        self.filesystem = filesystem

        if not options:
            options = "defaults"

        self.options = options
        self.d = d
        self.p = p

    def __eq__(self, o):
        return str(self) == str(o)

    def __ne__(self, o):
        return str(self) != str(o)

    def __str__(self):
        return "{0} {1} {2} {3} {4} {5}".format(self.device, self.mountpoint, self.filesystem, self.options, self.d, self.p)
