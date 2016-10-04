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
from source.tools.configuration.configuration import Configuration

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
        data['_version'] = 2
        data['_duration'] = time.time() - start
        return Response(json.dumps(data), content_type='application/json', status=status)

    new_function.__name__ = f.__name__
    new_function.__module__ = f.__module__
    return new_function


def _authorized():
    """
    Indicates whether a call is authenticated
    """
    username = Configuration.get('/ovs/alba/asdnodes/{0}/config/main|username'.format(NODE_ID))
    password = Configuration.get('/ovs/alba/asdnodes/{0}/config/main|password'.format(NODE_ID))
    auth = request.authorization
    return auth and auth.username == username and auth.password == password
