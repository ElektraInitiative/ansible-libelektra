#!/usr/bin/python

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: elektra

short_description: libelektra interface

version_added: "2.8.6"

description:
    - "This module is used to manage configurations using libelektra"

options:
    mountpoint:
        description:
            - mountpoint of the configuration
        required: true
    filename:
        description:
            - name of the configuration that to be mounted
        required: false
    resolver:
        description:
            - which resolver should be used for the backend
        required: false
    plugins:
        description:
            - list of plugins to be used as backend and their configuration
        required: true
    recommends:
        description:
            - use recommended plugins
        required: false
    keeporder:
        description:
            - use "order" metadata to preserve the order of the passed keyset
    keys:
        description:
            - keyset to write
        required: false
author:
    - Thomas Waser
'''

EXAMPLES = '''
# mount /etc/hosts with recommends to system:/hosts and set localhost to 127.0.0.1
- name: update localhost ip
  elektra:
    mountpoint: system:/hosts
    filename: /etc/hosts
    recommends: True
    plugins:
        - hosts:
    keys:
        ipv4:
            localhost: 127.0.0.1

# mount /tmp/test.ini to system:/testini using the ini plugin and ':' as separator instead of '='
# and replace "key: value" with "key: newvalue"
- name: mount ini
  elektra:
      mountpoint: system:/testini
      filename: /tmp/test.ini
      plugins:
        - ini:
            delimiter: ':'
      keys:
        key: newvalue
'''

RETURN = '''
'''


from ansible.module_utils.basic import AnsibleModule
from subprocess import check_output, PIPE, CalledProcessError
import kdb
from collections import OrderedDict

class ElektraException(Exception):
    """ elektraException """
    pass

class ElektraMountException(ElektraException):
    """Mount failed"""
    pass
class ElektraUmountException(ElektraException):
    """Umount failed"""
    pass
class ElektraReadException(ElektraException):
    """Failed to read keyset"""
    pass
class ElektraWriteException(ElektraException):
    """Failed to write keyset"""
    pass

# Flattens keyset except for "meta" or "value" dicts
def flatten_json(y):
    out = OrderedDict()
    def flatten(x, name=''):
        if type(x) is dict:
            for a in x:
                if str(a) == "value":
                    try:
                        type(out[name[:-1]])
                    except:
                        out[name[:-1]] = {}
                    out[name[:-1]]['value'] = x[a]
                elif str(a) == "meta":
                    try:
                        type(out[name[:-1]])
                    except:
                        out[name[:-1]] = {}
                    out[name[:-1]]['meta'] = x[a]
                else:
                    flatten(x[a], name + a + '/')
        else:
            out[name[:-1]] = x
    flatten(y)
    return out

def elektraSet(mountpoint, keyset, keeporder):
    with kdb.KDB() as db:
        ks = kdb.KeySet(0)
        rc = 0
        try:
            rc = db.get(ks, mountpoint)
        except kdb.KDBException as e:
            raise ElektraReadException("KDB.get failed: {}".format(e))
        if rc == -1:
            raise ElektraReadException("Failed to read keyset below {}".format(mountpoint))
        flattenedKeyset = flatten_json(keyset)
        i = 0
        for name, value in flattenedKeyset.items():
            key = None
            kname = None
            try:
                key = ks[mountpoint+"/"+name]
                if keeporder and key.hasMeta("order"):
                    i = int((key.getMeta("order").value))+1
                if keeporder:
                    key.setMeta("order", str(i))
                    i += 1
            except KeyError:
                key = kdb.Key(mountpoint+"/"+name)
                if keeporder:
                    key.setMeta("order", str(i))
                    i += 1
                ks.append(key)
            if isinstance(value, dict):
                for sname, svalue in value.items():
                    if sname == 'value':
                        if key.value != str(svalue):
                            key.value = str(svalue)
                    elif sname == 'meta':
                        for mname, mvalue in svalue.items():
                            if key.getMeta(mname) != str(mvalue):
                                key.setMeta(mname, str(mvalue))
            else:
                if key.value != str(value):
                    key.value = str(value)
        try:
            rc = db.set(ks, mountpoint)
        except kdb.KDBException as e:
            raise ElektraWriteException("KDB.set failed: {}".format(e))
        if rc == -1:
            raise ElektraWriteException("Failed to write keyset to {}".format(mountpoint))
        return rc

def execute(command):
    try:
        output = check_output(command)
        return (0, output)
    except CalledProcessError as e:
        return (e.returncode, e.output)

def elektraMount(mountpoint, filename, resolver, plugins, recommends):
    with kdb.KDB() as db:
        ks = kdb.KeySet(0)
        mountpoints = "system:/elektra/mountpoints"
        rc = 0
        try:
            rc = db.get(ks, mountpoints)
        except kdb.KDBException as e:
            raise ElektraReadException("KDB.get failed: {}".format(e))
        if rc == -1:
            raise ElektraMountException("Failed to fetch elektra facts: failed to read system:/elektra/mountpoints.")
        searchKey = mountpoints +'/'+ mountpoint.replace('/', '\/')
        try:
            key = ks[searchKey]
            return (0, True)
        except KeyError:
            command = []
            command.append("kdb")
            command.append("mount")
            if recommends:
                command.append("--with-recommends")
            command.append("-R")
            command.append(resolver)
            command.append(filename)
            command.append(mountpoint)
            for item in plugins:
                for cname, cvalue in item.items():
                    command.append(str(cname))          # plugin
                    if isinstance(cvalue, dict):        # iterate plugin meta
                        for scname, scvalue in cvalue.items():
                            command.append(str(scname)+"="+str(scvalue))
            return execute(command)

def elektraUmount(mountpoint):
    with kdb.KDB() as db:
        ks = kdb.KeySet(0)
        mountpoints = "system:/elektra/mountpoints"
        rc = 0
        try:
            rc = db.get(ks, mountpoints)
        except kdb.KDBException as e:
            raise ElektraReadException("KDB.get failed: {}".format(e))
        if rc != 1:
            raise ElektraUmountException("Failed to fetch elektra facts: failed to read system:/elektra/mountpoints.")
        key = kdb.Key()
        key.name = mountpoints+'/'+mountpoint.replace('/', '\/')
        ks.cut(key)
        try:
            rc = db.set(ks, mountpoints)
        except kdb.KDBException as e:
            raise ElektraWriteException("KDB.set failed: {}".format(e))
        if rc != 1:
            raise ElektraUmountException("Failed to umount "+key.name)

def main():
    module = AnsibleModule(
            argument_spec=dict(
                mountpoint=dict(type='str', required=True),
                keys=dict(type='raw', default={}),
                recommends=dict(type='bool', default=True),         # mount with --with-recommends
                filename=dict(type='str', default=''),
                resolver=dict(type='str', default='resolver'),
                plugins=dict(type='list', elements='dict'),
                keeporder=dict(type='bool', default=False),         # if True: add "order" metakey for each "keys"-element based on the original argument order
                )
            )
    keys = module.params.get('keys')
    mountpoint = module.params.get('mountpoint')
    plugins = module.params.get('plugins')
    resolver = module.params.get('resolver')
    filename = module.params.get('filename')
    recommends = module.params.get('recommends')
    keeporder = module.params.get('keeporder')
    json_output={}                                                  
    json_output['changed'] = False

    if mountpoint[0] == '/':
        module.fail_json(msg="Cascading mountpoints currently not supported")
        return

    mountpointExists = True     # Indicates if mountpoint already exists prior to calling the module. If not/"False" unmount it on failure
    rc = 0
    if plugins or filename != '':
        try:
            rc, output = elektraMount(mountpoint, filename, resolver, plugins, recommends)
            if rc == 0 and output == True:
                mountpointExists = False
        except ElektraMountException as e:
            module.fail_json(msg="Failed to mount configuration {} to {}: {}".format(filename, mountpoint, e))
    try:
        rc = elektraSet(mountpoint, keys, keeporder)
    except ElektraWriteException as e:
        json_output['ERROR']=e
        try:
            if not mountpointExists:
                elektraUmount(mountpoint)
        except ElektraUmountException as e:
            module.fail_json(msg="Failed to unmount {}: {}".format(mountpoint, e))
        module.fail_json(msg="Failed to write configuration to {}: {}".format(mountpoint, e))
    if rc == 1:
        json_output['changed'] = True
    module.exit_json(**json_output)      


if __name__ == '__main__':
    main()
