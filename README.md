# ansible-libelektra

This is an Ansible module for [Elektra](https://github.com/ElektraInitiative/libelektra).

## Installing Ansible

You need Ansible 2.7 or newer for this module.
Some distros may ship Ansible using Python 2, which does not work with this module as it requires Python 3.
As recommended [here](https://docs.ansible.com/ansible/latest/reference_appendices/python_3_support.html) one way to get started is:

```sh
pip3 install ansible
```

## Installing the Module

### Ansible 2.9+

If you have Ansible 2.9 or newer, you can [install directly from Ansible Galaxy](https://galaxy.ansible.com/elektra_initiative/libelektra).

```sh
ansible-galaxy collection install elektra_initiative.libelektra
```

The following command should now be recognized, but fail because of a missing `mountpoint`:

```sh
ansible localhost -m elektra_initiative.libelektra.elektra
```

To output the contents of the `system:/` namespace, you can use:

```sh
ansible localhost -m elektra_initiative.libelektra.elektrafacts
```

### Ansible 2.7+

If you cannot use Ansible 2.9, but you have Ansible 2.7 or newer, you may install the module manually.

To get started, clone this repo and copy the directory `plugins/modules` to `~/.ansible/plugins/modules/elektra`.
(You should then have e.g. `~/.ansible/plugins/modules/elektra/elektra.py` on your system.)

```sh
mkdir -p ~/.ansible/plugins/modules/elektra
cp ./plugins/modules/* ~/.ansible/plugins/modules/elektra/
```

You may also follow a different [method of installing Ansible modules](https://docs.ansible.com/ansible/latest/dev_guide/developing_locally.html).

To confirm the installation worked, run

```sh
ansible localhost -m elektrafacts
```

This should output the contents of the `system:/` namespace.

Additionally, the following command should be recognized, but fail because of a missing `mountpoint`:

```sh
ansible localhost -m elektra
```

## Example Playbooks

To use the playbooks below, put them into a file e.g. `my-playbook.yml` and run them with `ansible-playbook`:

```sh
ansible-playbook my-playbook.yml
```

The module lets you set values in the KDB, mount configuration files and control session recording.
This process is idempotent, i.e. only if the stored values differ from the ones in the playbook, the KDB will be modified.
The change detection happens on a per-task basis.
If a single key with in a task needs an update, then all the keys in this task will be updated.
The process is also atomic.
If anything fails, everything will be rolled back.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example values
      elektra:
        mount:
          - mountpoint: system:/hosts
            file: /tmp/hosts
            includeRecommendedPlugins: true
            plugins:
              - hosts:
          - mountpoint: user:/tests/ansible
            file: ansible.toml
            plugins:
              - toml:
        keys:
          - system:
              hosts:
                ipv4:
                  libelektra.org: 1.2.3.4
          - user:/tests/ansible:
              fruit:
                cherry: cola
                apple: pie
                berries:
                    raspberry: pi
                    blueberry: muffin
              vegtables:
                tomato: ketchup
                potato: fries
```

## Metakeys, Arrays, Subkeys and other key options

For every key you can specify metadata, array values and subkeys.
To do this, you can specify a list with one or more of the following entries directly into the key:
- `meta`: meta keys of the keys.
- `array`: Use a TOML array to specify an Elektra array.
           If you want to set values and metadata on the array index directly, you can use the special name `'#'`.
           If you use `'#'` outside of `array`, it will be treated as part of the key name.
           This way you can also manually create Elektra arrays.
           See the `pets` and `friends` keys in the example below.
- `value`: the value of the key. 
           Same as if you specify `cherry: cola` in the example above.
           Mainly useful if you want to specify a value for a key within a key hierarchy (i.e. has child keys)
- `remove`: boolean value.
            If you specify `true`, then this key will be removed from the KDB.
            It will NOT affect keys below this key.
            If you want to remove an entire subtree, see the top-level `remove` option further down. 
- `keys`: if this is a parent key of child keys, you can continue specifying the child keys below this.
          Obviously this is only needed if you use `value`, `meta` or `array`.
          You can nest this however often you like.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example keys
      elektra:
        keys:
          - 'user:/tests/ansible':
              fruit:
                cherry:
                  - value: cola
                  - meta:
                      type: string
                  - keys:
                      pie: yummy
                      jelly:
                        sugar: none
              pets:
                - array:
                    - name: rufus
                      type: dog
                    - name: bessie
                      type: cow
              friends:
                - meta:
                    complete: false
                - array:
                    - '#': Mary
                    - '#':
                        - value: John
                        - meta:
                            age: 53
```

The above example will generate the following keys:
- `user:/test/ansible/fruit/cherry = cola`
  - `meta:/type = string`
- `user:/test/ansible/fruit/cherry/pie = yummy`
- `user:/test/ansible/fruit/cherry/jelly/sugar = none`

- `user:/test/ansible/pets/#0/name = rufus` 
- `user:/test/ansible/pets/#0/type = dog`
- `user:/test/ansible/pets/#1/name = bessie`
- `user:/test/ansible/pets/#1/type = cow`

- `user:/test/ansible/friends`
  - `meta:/complete = false` 
- `user:/test/ansible/friends/#0 = Mary`
- `user:/test/ansible/friends/#1 = John`
  - `meta:/age = 53`

## Session Recording

You can control Elektra's session recording mechanism with this module.
The `recording` element has the following parameters:
- `skip`: `true` or `false`.
           This option MUST be set to `true` if the user executing this task does not have the privileges to write into the `system:/` namespace.
           By default, this is `false`.
           Will prevent the module from doing anything related to session recording.
           This also means that the changes performed during this task MAY be recorded depending on the state of session recording on the host.
           We recommend that you add another task before that disables session recording, and based on your needs another one afterwards that enables it again.
- `enable`: `true` or `false`. 
            Whether session recording should be enabled after the task is complete.
            By default, we enable this.
- `parentKey`: The parent key to use for session recording.
               Every change to this key or below will be recorded.
- `reset`: `true` or `false` 
            Whether the current recording session should be reset.
            All keys from the recording session will be removed.
            By default, we reset it.
- `recordAnsible`: `true` or `false`.
                   Whether changes made to Elektra via this task should be recorded.
                   By default, we do not do this.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: Interact with recording session
      elektra:
        recording:
          enable: true
          reset: true
          parentKey: user:/myapp
          recordAnsible: true
```

## Merging

You can force a 3-way merge to be used to merge the keys with existing changes on a host.
The `merge` element has the following parameters:
- `strategy`: The strategy to use to resolve merge conflicts. Either one of:
  - `ours`: use the keys specified in this tasks on conflict.
  - `theirs`: use the keys on the host on conflict.
  - `abort`: abort task on conflict.
- `base`: If specified, this is the base keyset to use as the _base_ in the 3-way merge.
          It has the same syntax as the `keys` element of the task.
          If not specified, we will try to generate the base keys from the current configuration on the host.
          If the recording session on the host contains changes, we will undo them from the base.

## Key Removal

There are two slightly different ways how keys can be removed.
The first one is the already mentioned `remove` option on the key itself.

If specified, it will remove the single key it is attached to.
Other things such as `meta` and `value` will have no effect.
The `array` and `keys` option will still work as expected.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example keys
      elektra:
        keys:
          - system:/hosts:
              example.com:
                - remove: true
```

The second one, is the top-level `remove` option.
`remove`: A list of keys that shall be removed.

One big differences in this approach is the parameter.
You may specify the parameter `recursive` as `true` to also remove the children of the key, allowing you to remove the entire subtree from the KDB.

The following example will remove the key `user:/ansible/test` and everything below `system:/hosts`:

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example keys
      elektra:
        remove:
          - user:/ansible/test
          - system:/hosts:
              recursive: true
```

The second big difference is the interaction with the `value` and `meta` options specified in `keys`.
If you use the top-level `remove` option, you can still add this key in the `keys` option.
This allows you to ensure that the key gets added to the KDB as you describe.

Normally, the meta data of the existing key would get merged with the meta data you specify in the playbook.
If you specify the key in the top-level `remove` then the existing key gets removed and the new key gets added as-is.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example keys
      elektra:
        remove:
          - user:/ansible/test
        keys:
          - user:
              ansible:
                test:
                  - value: hello
                  - meta:
                      description: I will be the only meta-key in the KDB for this key!
```

## Other Options

`keepOrder`: `true` or `false`.
If specified, we will try to keep the order (using the `meta:/order` meta key) for keys contained in this task.
By default, this option is disabled (`false`).

The following example will 'force' the hosts plugin to write the `example.org` hosts after `libelektra.org` into the hosts file.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example keys
      elektra:
        keepOrder: true
        keys:
          - system:
              hosts:
                ipv4:
                  libelektra.org: 1.2.3.4
                  example.org: 127.0.0.2
```
