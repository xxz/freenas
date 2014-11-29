#+
# Copyright 2014 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################

import errno
from gevent.event import Event
from dispatcher.rpc import RpcService, RpcException, pass_sender


class ManagementService(RpcService):
    def initialize(self, context):
        self.context = context
        self.dispatcher = context.dispatcher

    def status(self):
        return {
            'started-at': self.dispatcher.started_at,
            'connected-clients': len(self.dispatcher.ws_server.connections)
        }

    def reload_plugins(self):
        self.dispatcher.reload_plugins()

    def restart(self):
        pass

    def get_event_sources(self):
        return self.dispatcher.event_sources.keys()

    def get_connected_clients(self):
        return self.dispatcher.ws_server.clients.keys()

    def die_you_gravy_sucking_pig_dog(self):
        self.dispatcher.die()


class EventService(RpcService):
    def initialize(self, context):
        self.__datastore = context.dispatcher.datastore
        self.__dispatcher = context.dispatcher
        pass

    def query(self, mask, start=None, end=None, limit=None):
        where = []
        if start is not None:
            where.append(('timestamp', '>=', start))

        if end is not None:
            where.append(('timestamp', '<=', end))

        return list(self.__datastore.query('events', where, limit))


class PluginService(RpcService):
    class RemoteServiceWrapper(RpcService):
        def __init__(self, connection, name):
            self.connection = connection
            self.service_name = name

        def enumerate_methods(self):
            return list(self.connection.call_client_sync(self.service_name + '.enumerate_methods'))

        def __getattr__(self, name):
            def call_wrapped(*args):
                return self.connection.call_client_sync(
                    '.'.join([self.service_name, name]),
                    *args)

            return call_wrapped

    def __client_disconnected(self, args):
        for name, svc in self.services.items():
            if args['address'] == svc.connection.ws.handler.client_address:
                self.unregister_service(name, svc.connection)

    def initialize(self, context):
        self.services = {}
        self.events = {}
        self.__dispatcher = context.dispatcher
        self.__dispatcher.register_event_handler(
            'server.client_disconnected',
            self.__client_disconnected)

    @pass_sender
    def register_service(self, name, sender):
        wrapper = self.RemoteServiceWrapper(sender, name)
        self.services[name] = wrapper
        self.__dispatcher.rpc.register_service_instance(name, wrapper)
        self.__dispatcher.dispatch_event('plugin.service_registered', {
            'address': sender.ws.handler.client_address,
            'service-name': name,
            'description': "Service {0} registered".format(name)
        })

        if name in self.events.keys():
            self.events[name].set()

    @pass_sender
    def unregister_service(self, name, sender):
        if name not in self.services.keys():
            raise RpcException(errno.ENOENT, 'Service not found')

        svc = self.services[name]
        if svc.connection != sender:
            raise RpcException(errno.EPERM, 'Permission denied')

        self.__dispatcher.rpc.unregister_service(name)
        self.__dispatcher.dispatch_event('plugin.service_unregistered', {
            'address': sender.ws.handler.client_address,
            'service-name': name,
            'description': "Service {0} unregistered".format(name)
        })

        del self.services[name]

    def wait_for_service(self, name, timeout=None):
        if name in self.services.keys():
            return

        self.events[name] = Event()
        self.events[name].wait(timeout)
        del self.events[name]


class TaskService(RpcService):
    def initialize(self, context):
        self.__datastore = context.dispatcher.datastore
        self.__balancer = context.dispatcher.balancer
        pass

    def submit(self, name, args):
        tid = self.__balancer.submit(name, args)
        return tid

    def status(self, id):
        t = self.__datastore.get_by_id('tasks', id)
        task = self.__balancer.get_task(id)

        if task:
            t['progress'] = task.progress.__getstate__()

        return t

    def abort(self, id):
        self.__balancer.abort(id)

    def list_queues(self):
        result = []
        for name, queue in self.__balancer.queues.items():
            result.append({
                "name": name,
                "type": queue.clazz,
                "status": queue.worker.state
            })

        return result

    def list_tasks(self, limit=None):
        result = []
        for t in self.__datastore.query('tasks', sort='created_at', dir='desc', limit=limit):
            result.append(t)

        return result

    def list_active(self):
        result = []
        for i in self.__balancer.get_active_tasks():
            result.append({
                "id": i.id,
                "type": i.name,
                "state": i.state
            })

        return result

    def list_failed(self):
        result = []
        from balancer import TaskState
        for i in self.__balancer.get_tasks(TaskState.FAILED):
            result.append({
                "id": i.id,
                "type": i.name,
                "state": i.state
            })

        return result