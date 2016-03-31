# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
FSTAB related code
"""


class FSTab(object):
    filename = '/etc/fstab'
    separator = ('# BEGIN ALBA ASDs', '# END ALBA ASDs')  # Don't change, for backwards compatibility
    line = '{0}  {1}  xfs  defaults,nobootwait,noatime,discard  0  2'

    @staticmethod
    def add(disk, mountpoint):
        lines = FSTab._read()
        found = False
        for line in lines:
            if line.startswith(disk):
                found = True
                break
        if found is False:
            lines.append(FSTab.line.format(disk, mountpoint))
        FSTab._write(lines)

    @staticmethod
    def remove(disk):
        lines = FSTab._read()
        new_lines = []
        for line in lines:
            if disk not in line:
                new_lines.append(line)
        FSTab._write(new_lines)

    @staticmethod
    def read():
        lines = FSTab._read()
        disks = {}
        for line in lines:
            device, mountpoint, _ = line.split('  ', 2)
            device = device.split('/')[-1].replace('-part1', '')
            disks[device] = mountpoint
        return disks

    @staticmethod
    def _read():
        lines = []
        with open(FSTab.filename, 'r') as fstab:
            contents = fstab.read().strip()
        while '\n\n\n' in contents:
            contents = contents.replace('\n\n\n', '\n\n')
        contents = contents.split('\n')
        skip = True
        for line in contents:
            if line.startswith(FSTab.separator[1]):
                skip = True
            if skip is False:
                lines.append(line)
            if line.startswith(FSTab.separator[0]):
                skip = False
        return lines

    @staticmethod
    def _write(lines):
        with open(FSTab.filename, 'r') as fstab:
            contents = fstab.read().strip()
        while '\n\n\n' in contents:
            contents = contents.replace('\n\n\n', '\n\n')
        contents = contents.split('\n')
        new_content = []
        skip = False
        for line in contents:
            if line.startswith(FSTab.separator[0]):
                skip = True
            if skip is False:
                new_content.append(line)
            if line.startswith(FSTab.separator[1]):
                skip = False
        new_content.append(FSTab.separator[0])
        new_content += lines
        new_content.append(FSTab.separator[1])
        with open(FSTab.filename, 'w') as fstab:
            fstab.write('{0}\n'.format('\n'.join(new_content)))
