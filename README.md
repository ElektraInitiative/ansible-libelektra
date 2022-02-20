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

The module lets you set values in the KDB.
This process is idempotent, i.e. only if the stored values differ from the ones in the playbook, the KDB will be modified.
The change detection happens on a per-task basis.
If a single key with in a task needs an update, then all the keys in this task will be updated.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example values
      elektra:
        # Despite the name, this does not have to be a real mountpoint in the KDB.
        # If no plugin is specified, the value is only used as the base key for the keys object.
        mountpoint: user:/test/example
        # The keys object contains the data that should be present below the mountpoint.
        keys:
          fruit:
            cherry:
              value: cola
            apple:
              value: pie
            berries:
                raspberry:
                  value: pi
                blueberry:
                  value: muffin
          vegtables:
            tomato:
              value: ketchup
            potato:
              value: fries

```

You can also specify metadata (if the underlying storage format supports it).
In most cases, you should use a specification for metadata instead.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  collections:
    - elektra_initiative.libelektra
  tasks:
    - name: set example fruits
      elektra:
        mountpoint: user:/test/example/fruit
        keys:
          cherry:
            value: cola
            meta:
              # This adds the type metakey with value string to the key /test/example/fruit/cherry
              type: string
          apple:
            value: pie
          berries:
              raspberry:
                value: pi
              blueberry:
                value: muffin
    - name: set example vegetables
      elektra:
        mountpoint: user:/test/example/vegetables
        keys:
          tomato:
              value: ketchup
          potato:
              value: fries
```
