#!/usr/bin/python2
# Copyright 2015 CloudFounders NV
# All rights reserved


from app import app
from tools.configuration import Configuration

if __name__ == '__main__':
    context = ('server.crt', 'server.key')
    app.run(host='0.0.0.0',
            port=int(Configuration.get('ports.service')),
            debug=True,
            ssl_context=context)
