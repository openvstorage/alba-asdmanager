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
LocalClient module
Used for local command execution
"""

import os
import re
import grp
import pwd
import glob
import json
import time
import types
import select
import socket
import logging
import tempfile
from subprocess import CalledProcessError, PIPE, Popen
from source.tools.log_handler import LogHandler


class LocalClient(object):
    """
    Local client
    """

    _logger = LogHandler.get('asd-manager', name='client')
    client_cache = {}
    IP_REGEX = re.compile('^(((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?))$')
    _run_returns = {}
    _run_recordings = []

    def __init__(self, endpoint='127.0.0.1', username='root', password=None):
        """
        Initializes a LocalClient
        """
        from subprocess import check_output
        if isinstance(endpoint, basestring):
            ip = endpoint
            if not re.findall(SSHClient.IP_REGEX, ip):
                raise ValueError('Incorrect IP {0} specified'.format(ip))
        else:
            raise ValueError('The endpoint parameter should be an ip address')

        self.ip = ip
        self.local_ips = [lip.strip() for lip in check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True).strip().splitlines()]
        if slf.ip not in self.local_ips:
            raise ValueError('The client can only connect to the local host')
        self.password = password

        current_user = check_output('whoami', shell=True).strip()
        if username is None:
            self.username = current_user
        else:
            self.username = username
            if username != current_user:
                raise ValueError('Switching users is not supported')

    @staticmethod
    def shell_safe(argument):
        """
        Makes sure that the given path/string is escaped and safe for shell
        :param argument: Argument to make safe for shell
        """
        return "'{0}'".format(argument.replace(r"'", r"'\''"))

    @staticmethod
    def _clean_text(text):
        if type(text) is list:
            text = '\n'.join(line.rstrip() for line in text)
        try:
            # This strip is absolutely necessary. Without it, channel.communicate() is never executed (odd but true)
            if isinstance(text, unicode):
                cleaned = text.strip()
            else:
                cleaned = text.strip().decode('utf-8', 'replace')
            for old, new in {u'\u2018': "'",
                             u'\u201a': "'",
                             u'\u201e': '"',
                             u'\u201c': '"',
                             u'\u25cf': '*'}.iteritems():
                cleaned = cleaned.replace(old, new)
            return cleaned
        except UnicodeDecodeError:
            LocalClient._logger.error('UnicodeDecodeError with output: {0}'.format(text))
            raise

    @connected()
    def run(self, command, debug=False, suppress_logging=False, allow_nonzero=False, allow_insecure=False):
        """
        Executes a shell command
        :param suppress_logging: Do not log anything
        :param command: Command to execute
        :param debug: Extended logging and stderr output returned
        :param allow_nonzero: Allow non-zero exit code
        :param allow_insecure: Allow string commands (which might be inproper escaped)
        """

        if not isinstance(command, list) and not allow_insecure:
            raise RuntimeError('The given command must be a list, or the allow_insecure flag must be set')

        stderr = None
        try:
            try:
                if not hasattr(select, 'poll'):
                    import subprocess
                    subprocess._has_poll = False  # Damn 'monkey patching'
                channel = Popen(command, stdout=PIPE, stderr=PIPE, shell=not isinstance(command, list))
            except OSError as ose:
                raise CalledProcessError(1, command, str(ose))
            stdout, stderr = channel.communicate()
            stdout = self._clean_text(stdout)
            stderr = self._clean_text(stderr)
            exit_code = channel.returncode
            if exit_code != 0 and allow_nonzero is False:  # Raise same error as check_output
                raise CalledProcessError(exit_code, command, stdout)
            if debug:
                LocalClient._logger.debug('stdout: {0}'.format(stdout))
                LocalClient._logger.debug('stderr: {0}'.format(stderr))
                return stdout, stderr
            else:
                return stdout
        except CalledProcessError as cpe:
            if suppress_logging is False:
                LocalClient._logger.error('Command "{0}" failed with output "{1}"{2}'.format(
                    command, cpe.output, '' if stderr is None else ' and error "{0}"'.format(stderr)
                ))
            raise

    def dir_create(self, directories):
        """
        Ensures a directory exists on the remote end
        :param directories: Directories to create
        """
        _ = self
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory)

    def dir_delete(self, directories, follow_symlinks=False):
        """
        Remove a directory (or multiple directories) from the remote filesystem recursively
        :param directories: Single directory or list of directories to delete
        :param follow_symlinks: Boolean to indicate if symlinks should be followed and thus be deleted too
        """
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            real_path = self.file_read_link(directory)
            if real_path and follow_symlinks is True:
                self.file_unlink(directory.rstrip('/'))
                self.dir_delete(real_path)
            else:
                if os.path.exists(directory):
                    for dirpath, dirnames, filenames in os.walk(directory, topdown=False, followlinks=follow_symlinks):
                        for filename in filenames:
                            os.remove('/'.join([dirpath, filename]))
                        for sub_directory in dirnames:
                            os.rmdir('/'.join([dirpath, sub_directory]))
                    os.rmdir(directory)

    def dir_exists(self, directory):
        """
        Checks if a directory exists on a remote host
        :param directory: Directory to check for existence
        """
        _ = self
        return os.path.isdir(directory)

    def dir_chmod(self, directories, mode, recursive=False):
        """
        Chmod a or multiple directories
        :param directories: Directories to chmod
        :param mode: Mode to chmod
        :param recursive: Chmod the directories recursively or not
        :return: None
        """
        _ = self
        if not isinstance(mode, int):
            raise ValueError('Mode should be an integer')

        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            os.chmod(directory, mode)
            if recursive is True:
                for root, dirs, _ in os.walk(directory):
                    for sub_dir in dirs:
                        os.chmod('/'.join([root, sub_dir]), mode)

    def dir_chown(self, directories, user, group, recursive=False):
        """
        Chown a or multiple directories
        :param directories: Directories to chown
        :param user: User to assign to directories
        :param group: Group to assign to directories
        :param recursive: Chown the directories recursively or not
        :return: None
        """
        _ = self
        all_users = [user_info[0] for user_info in pwd.getpwall()]
        all_groups = [group_info[0] for group_info in grp.getgrall()]

        if user not in all_users:
            raise ValueError('User "{0}" is unknown on the system'.format(user))
        if group not in all_groups:
            raise ValueError('Group "{0}" is unknown on the system'.format(group))

        uid = pwd.getpwnam(user)[2]
        gid = grp.getgrnam(group)[2]
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            os.chown(directory, uid, gid)
            if recursive is True:
                for root, dirs, _ in os.walk(directory):
                    for sub_dir in dirs:
                        os.chown('/'.join([root, sub_dir]), uid, gid)

    def dir_list(self, directory):
        """
        List contents of a directory on a remote host
        :param directory: Directory to list
        """
        _ = self
        return os.listdir(directory)

    def symlink(self, links):
        """
        Create symlink
        :param links: Dictionary containing the absolute path of the files and their link which needs to be created
        :return: None
        """
        _ = self
        for link_name, source in links.iteritems():
            os.symlink(source, link_name)

    def file_create(self, filenames):
        """
        Create a or multiple files
        :param filenames: Files to create
        :return: None
        """
        if isinstance(filenames, basestring):
            filenames = [filenames]
        for filename in filenames:
            if not filename.startswith('/'):
                raise ValueError('Absolute path required for filename {0}'.format(filename))

            if not self.dir_exists(directory=os.path.dirname(filename)):
                self.dir_create(os.path.dirname(filename))
            if not os.path.exists(filename):
                open(filename, 'a').close()

    def file_delete(self, filenames):
        """
        Remove a file (or multiple files) from the remote filesystem
        :param filenames: File names to delete
        """
        _ = self
        if isinstance(filenames, basestring):
            filenames = [filenames]
        for filename in filenames:
            if '*' in filename:
                for fn in glob.glob(filename):
                    os.remove(fn)
            else:
                if os.path.isfile(filename):
                    os.remove(filename)

    def file_unlink(self, path):
        """
        Unlink a file
        :param path: Path of the file to unlink
        :return: None
        """
        _ = self
        if os.path.islink(path):
            os.unlink(path)

    def file_read_link(self, path):
        """
        Read the symlink of the specified path
        :param path: Path of the symlink
        :return: None
        """
        _ = self
        path = path.rstrip('/')
        if os.path.islink(path):
            return os.path.realpath(path)

    def file_read(self, filename):
        """
        Load a file from the remote end
        :param filename: File to read
        """
        _ = self
        with open(filename, 'r') as the_file:
            return the_file.read()

    @connected()
    def file_write(self, filename, contents, mode='w'):
        """
        Writes into a file to the remote end
        :param filename: File to write
        :param contents: Contents to write to the file
        :param mode: Mode to write to the file, can be a, a+, w, w+
        """
        _ = self
        with open(filename, mode) as the_file:
            the_file.write(contents)

    @connected()
    def file_upload(self, remote_filename, local_filename):
        """
        Uploads a file to a remote end
        :param remote_filename: Name of the file on the remote location
        :param local_filename: Name of the file locally
        """
        self.run(['cp', '-f', local_filename, remote_filename])

    def file_exists(self, filename):
        """
        Checks if a file exists on a remote host
        :param filename: File to check for existence
        """
        _ = self
        return os.path.isfile(filename)

    def file_chmod(self, filename, mode):
        """
        Sets the mode of a remote file
        :param filename: File to chmod
        :param mode: Mode to give to file, eg: 0744
        """
        self.run(['chmod', str(mode), filename])

    def file_chown(self, filenames, user, group):
        """
        Sets the ownership of a remote file
        :param filenames: Files to chown
        :param user: User to set
        :param group: Group to set
        :return: None
        """
        all_users = [user_info[0] for user_info in pwd.getpwall()]
        all_groups = [group_info[0] for group_info in grp.getgrall()]

        if user not in all_users:
            raise ValueError('User "{0}" is unknown on the system'.format(user))
        if group not in all_groups:
            raise ValueError('Group "{0}" is unknown on the system'.format(group))

        uid = pwd.getpwnam(user)[2]
        gid = grp.getgrnam(group)[2]
        if isinstance(filenames, basestring):
            filenames = [filenames]
        for filename in filenames:
            if self.file_exists(filename=filename) is False:
                continue
            os.chown(filename, uid, gid)

    def file_list(self, directory, abs_path=False, recursive=False):
        """
        List all files in directory
        WARNING: If executed recursively while not locally, this can take quite some time

        :param directory: Directory to list the files in
        :param abs_path: Return the absolute path of the files or only the file names
        :param recursive: Loop through the directories recursively
        :return: List of files in directory
        """
        _ = self
        all_files = []
        for root, dirs, files in os.walk(directory):
            for file_name in files:
                if abs_path is True:
                    all_files.append('/'.join([root, file_name]))
                else:
                    all_files.append(file_name)
            if recursive is False:
                break
        return all_files

    def is_mounted(self, path):
        """
        Verify whether a mountpoint is mounted
        :param path: Path to check
        :type path: str

        :return: True if mountpoint is mounted
        :rtype: bool
        """
        _ = self
        path = path.rstrip('/')
        return os.path.ismount(path)

    def get_hostname(self):
        """
        Gets the simple and fq domain name
        """
        short = self.run(['hostname', '-s'])
        try:
            fqdn = self.run(['hostname', '-f'])
        except:
            fqdn = short
        return short, fqdn
