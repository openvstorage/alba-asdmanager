# Copyright 2015 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from subprocess import check_output, CalledProcessError, PIPE, Popen

import os
import re
import grp
import pwd
import glob


class LocalClient(object):
    """
    Local client
    """

    IP_REGEX = re.compile('^(((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?))$')

    def __init__(self, endpoint='127.0.0.1', username='root', password=None):
        """
        Initializes an SSHClient
        """
        storagerouter = None
        if isinstance(endpoint, basestring):
            ip = endpoint
            if not re.findall(SSHClient.IP_REGEX, ip):
                raise ValueError('Incorrect IP {0} specified'.format(ip))
        else:
            raise ValueError('The endpoint parameter should be either an ip address or a StorageRouter')

        self.ip = ip
        local_ips = check_output("ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1", shell=True).strip().splitlines()
        self.local_ips = [lip.strip() for lip in local_ips]
        self.is_local = self.ip in self.local_ips
        if self.is_local is False:
            raise ValueError('This is not an SSHClient.')

        current_user = check_output('whoami', shell=True).strip()
        if username is None:
            self.username = current_user
        else:
            self.username = username
            if username != current_user:
                self.is_local = False  # If specified user differs from current executing user, we always use the paramiko SSHClient
        self.password = password
        self.client = None


    @staticmethod
    def shell_safe(path_to_check):
        """
        Makes sure that the given path/string is escaped and safe for shell
        :param path_to_check: Path to make safe for shell
        """
        return "".join([("\\" + _) if _ in " '\";`|" else _ for _ in path_to_check])

    def run(self, command, debug=False, suppress_logging=False):
        """
        Executes a shell command
        :param suppress_logging: Do not log anything
        :param command: Command to execute
        :param debug: Extended logging and stderr output returned
        """

        try:
            try:
                process = Popen(command, stdout=PIPE, stderr=PIPE, shell=True)
            except OSError as ose:
                if suppress_logging is False:
                    print('Command: "{0}" failed with output: "{1}"'.format(command, str(ose)))
                raise CalledProcessError(1, command, str(ose))
            out, err = process.communicate()
            if debug:
                print('stdout: {0}'.format(out))
                print('stderr: {0}'.format(err))
                return out.strip(), err
            else:
                return out.strip()

        except CalledProcessError as cpe:
            if suppress_logging is False:
                print('Command: "{0}" failed with output: "{1}"'.format(command, cpe.output))
            raise cpe

    def dir_create(self, directories):
        """
        Ensures a directory exists
        :param directories: Directories to create
        """
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            directory = self.shell_safe(directory)
            if not os.path.exists(directory):
                os.makedirs(directory)

    def dir_delete(self, directories, follow_symlinks=False):
        """
        Remove a directory (or multiple directories)
        :param directories: Single directory or list of directories to delete
        :param follow_symlinks: Boolean to indicate if symlinks should be followed and thus be deleted too
        """
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            directory = self.shell_safe(directory)
            real_path = self.file_read_link(directory)
            if real_path and follow_symlinks is True:
                self.file_unlink(directory.rstrip('/'))
                self.dir_delete(real_path)
            else:
                if os.path.exists(directory):
                    for dirpath, dirnames, filenames in os.walk(directory, topdown=False, followlinks=follow_symlinks):
                        for filename in filenames:
                            os.remove(os.path.join(dirpath, filename))
                        for sub_directory in dirnames:
                            os.rmdir(os.path.join(dirpath, sub_directory))
                    os.rmdir(directory)

    def dir_exists(self, directory):
        """
        Checks if a directory exists
        :param directory: Directory to check for existence
        """
        return os.path.isdir(self.shell_safe(directory))


    def dir_chmod(self, directories, mode, recursive=False):
        """
        Chmod a or multiple directories
        :param directories: Directories to chmod
        :param mode: Mode to chmod
        :param recursive: Chmod the directories recursively or not
        :return: None
        """
        if not isinstance(mode, int):
            raise ValueError('Mode should be an integer')

        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            directory = self.shell_safe(directory)
            os.chmod(directory, mode)
            if recursive is True:
                for root, dirs, _ in os.walk(directory):
                    for sub_dir in dirs:
                        os.chmod(os.path.join(root, sub_dir), mode)

    def dir_chown(self, directories, user, group, recursive=False):
        """
        Chown a or multiple directories
        :param directories: Directories to chown
        :param user: User to assign to directories
        :param group: Group to assign to directories
        :param recursive: Chown the directories recursively or not
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
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            directory = self.shell_safe(directory)
            os.chown(directory, uid, gid)
            if recursive is True:
                for root, dirs, _ in os.walk(directory):
                    for sub_dir in dirs:
                        os.chown(os.path.join(root, sub_dir), uid, gid)

    def dir_list(self, directory):
        """
        List contents of a directory
        :param directory: Directory to list
        """
        return os.listdir(self.shell_safe(directory))

    def symlink(self, links):
        """
        Create symlink
        :param links: Dictionary containing the absolute path of the files and their link which needs to be created
        :return: None
        """
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
            filename = self.shell_safe(filename)
            if not self.dir_exists(directory=os.path.dirname(filename)):
                self.dir_create(os.path.dirname(filename))
            if not os.path.exists(filename):
                open(filename, 'a').close()

    def file_delete(self, filenames):
        """
        Remove a file (or multiple files)
        :param filenames: File names to delete
        """
        if isinstance(filenames, basestring):
            filenames = [filenames]
        for filename in filenames:
            filename = self.shell_safe(filename)
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
        path = self.shell_safe(path)
        if os.path.islink(path):
            os.unlink(path)

    def file_read_link(self, path):
        """
        Read the symlink of the specified path
        :param path: Path of the symlink
        :return: None
        """
        path = self.shell_safe(path.rstrip('/'))
        if os.path.islink(path):
            return os.path.realpath(path)


    def file_read(self, filename):
        """
        Load a file from
        :param filename: File to read
        """
        with open(filename, 'r') as the_file:
            return the_file.read()

    def file_write(self, filename, contents, mode='w'):
        """
        Writes into a file
        :param filename: File to write
        :param contents: Contents to write to the file
        :param mode: Mode to write to the file, can be a, a+, w, w+
        """
        with open(filename, mode) as the_file:
            the_file.write(contents)

    def file_upload(self, remote_filename, local_filename):
        """
        Uploads a file to a remote end
        :param remote_filename: Name of the file on the remote location
        :param local_filename: Name of the file locally
        """
        check_output('cp -f "{0}" "{1}"'.format(local_filename, remote_filename), shell=True)


    def file_exists(self, filename):
        """
        Checks if a file exists
        :param filename: File to check for existence
        """
        return os.path.isfile(self.shell_safe(filename))

    def file_attribs(self, filename, mode):
        """
        Sets the mode of a file
        :param filename: File to chmod
        :param mode: Mode to give to file, eg: 0744
        """
        command = 'chmod {0} "{1}"'.format(mode, filename)
        check_output(command, shell=True)
