#!/usr/bin/python


from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.facts import *
import kdb

def main():
    module = AnsibleModule(
            argument_spec=dict(
                mountpoint=dict(default='system:/'),
                )
            )
    mountpoint = module.params.get('mountpoint')
    json_output={}                                                  
    with kdb.KDB() as db:
        ks = kdb.KeySet(0)
        rc = db.get(ks, mountpoint)
        if rc != 1:
            module.fail_json(msg="No configuration mounted under %s" % mountpoint)
        for k in ks:
            kname=str(k)[len(mountpoint):].rstrip("/")
            miter=k.getMeta()
            if miter != None:
                json_output[kname] = {}
                json_output[kname]['value']=k.value
                for m in miter:
                    json_output[kname][str(m)] = m.value
            else:
                json_output[kname] = k.value

    module.exit_json(**json_output)      

if __name__ == '__main__':
    main()
