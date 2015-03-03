# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API decorators
"""

from tools.configuration import Configuration
from flask import request, Response


def requires_auth():
    """
    Method decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        def new_function(*args, **kwargs):
            """
            Wrapped function
            """
            auth = request.authorization
            if not auth or auth.username != Configuration.get('main.username') or auth.password != Configuration.get('main.password'):
                return Response('Invalid credentials', 401)
            return f(*args, **kwargs)

        new_function.__name__ = f.__name__
        new_function.__module__ = f.__module__
        return new_function
    return wrap
