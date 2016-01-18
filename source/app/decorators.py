# Copyright 2014 iNuron NV
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

"""
API decorators
"""

import os
import json
import time
import datetime
import traceback
import subprocess
from flask import request, Response
from source.app import app
from source.app.exceptions import APIException
from source.tools.configuration import EtcdConfiguration

NODE_ID = os.environ['ASD_NODE_ID']


def post(route, authenticate=True):
    """
    POST decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['POST'])(_build_function(f, authenticate))
    return wrap


def get(route, authenticate=True):
    """
    GET decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['GET'])(_build_function(f, authenticate))
    return wrap


def _build_function(f, authenticate):
    """
    Wrapping generator
    """
    def new_function(*args, **kwargs):
        """
        Wrapped function
        """
        start = time.time()
        if authenticate is True and not _authorized():
            data, status = {'_success': False,
                            '_error': 'Invalid credentials'}, 401
        else:
            try:
                return_data = f(*args, **kwargs)
                if return_data is None:
                    return_data = {}
                if isinstance(return_data, tuple):
                    data, status = return_data[0], return_data[1]
                else:
                    data, status = return_data, 200
                data['_success'] = True
                data['_error'] = ''
            except APIException as ex:
                print '{0} - {1}'.format(datetime.datetime.now(), traceback.print_exc())
                data, status = {'_success': False,
                                '_error': str(ex)}, ex.status_code
            except subprocess.CalledProcessError as ex:
                print '{0} - {1}'.format(datetime.datetime.now(), traceback.print_exc())
                data, status = {'_success': False,
                                '_error': ex.output}, 500
            except Exception as ex:
                print '{0} - {1}'.format(datetime.datetime.now(), traceback.print_exc())
                data, status = {'_success': False,
                                '_error': str(ex)}, 500
        data['_version'] = 1
        data['_duration'] = time.time() - start
        return Response(json.dumps(data), content_type='application/json', status=status)

    new_function.__name__ = f.__name__
    new_function.__module__ = f.__module__
    return new_function


def _authorized():
    """
    Indicates whether a call is authenticated
    """
    username = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|username'.format(NODE_ID))
    password = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|password'.format(NODE_ID))
    auth = request.authorization
    return auth and auth.username == username and auth.password == password
