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

## Metakeys, Arrays and Subkeys

For every key you can specify metadata, array values and subkeys.
To do this, you can specify a list with one or more of the following entries directly into the key:
- `meta`: meta keys of the keys.
- `array`: Use a TOML array to specify an Elektra array.
           If you want to set values and metadata on the array index directly, you can use the special name `'#'`.
           See the `pets` and `friends` keys in the example below.
- `value`: the value of the key. 
           Same as if you specify `cherry: cola` in the example above.
- `keys`: if this is a parent key of child keys, you can continue specifiyng the child keys below this.
          Obviously this is only needed if you use `value`, `meta` or `array`.
          You can nest this however often you like.

The following example will generate the following keys:
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
          - user:/tests/ansible:
              fruit:
                cherry:
                  - value: cola
                  - meta:
                      # This adds the type metakey with value string to the key /tests/ansible/fruit/cherry
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

## Session Recording

You can control Elektra's session recording mechanism with this module.
The `recording` element has the following parameters:
- `enable`: `true` or `false`. 
            Whether session recording should be enabled after the task is complete.
            By default, we enable this.
- `parentKey`: The parent key to use for session recording.
               Every change to this key or below will be recorded.
- `clear`: `true` or `false` 
            Whether the current recording session should be deleted.
            By default, we clear it.
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
    - name: set example keys
      elektra:
        recording:
          enable: true
          clear: true
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
          It has the same syntax as the `key` element of the task.
          If not specified, we will try to generate the base keys from the current configuration on the host.
          If the recording session on the host contains changes, we will undo them from the base.

## Other Options

`clear`: A list of keys that shall be removed, including their children.
The following example will remove everything below `user:/ansible/test` and `system:/host/ipv4`.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example keys
      elektra:
        clear:
          - user:/ansible/test
          - system:/hosts/ipv4
```

`keepOrder`: `true` or `false`.
If specified, we will try to keep the order (using the `meta:/order` meta key) for keys contained in this task.
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
        clear:
          - system:
              hosts:
                ipv4:
                  libelektra.org: 1.2.3.4
                  example.org: 127.0.0.2
```
