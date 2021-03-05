# ansible-libelektra

This is an Ansible module for [Elektra](https://github.com/ElektraInitiative/libelektra).

## Getting Ansible

We recommend you follow the instructions in the [official Ansible documentation](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html) instead of just installing from your distro's default repository.
Some distros may ship older versions of Ansible, which make it harder to install this module (see below).

## Installation

You need Ansible 2.7 or newer for this module.
Older Versions may work, but to install the module you would have to add the module directly into the Ansible source.

### Ansible 2.9+

If you have Ansible 2.9 or newer, you can [install directly from Ansible Galaxy](https://galaxy.ansible.com/ElektraInitiative/libelektra).

### Ansible 2.7+

If you cannot use Ansible 2.9, but you have Ansible 2.7 or newer, you may install the module manually.

To get started, clone this repo and copy the directory `elektra` to `~/.ansible/plugins/modules/elektra`.
(You should then have e.g. `~/.ansible/plugins/modules/elektra/elektra.py` on your system.)

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

The module lets you set values in the KDB.
This process is idempotent, i.e. only if the stored values differ from the ones in the playbook, will the KDB be modified.
The change detection happens on a per-task basis.
If a single key with in a task needs an update, the all the keys in this task will be updated.

```yml
- name: elektra module example
  hosts: localhost
  connection: local
  tasks:
    - name: set example values
      elektra:
        # Despite the name, this does not have to be a real mountpoint in the KDB.
        # If no plugin is specified, the value is only used as the base key for the keys object.
        mountpoint: /test/example
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
  tasks:
    - name: set example fruits
      elektra:
        mountpoint: /test/example/fruit
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
    - name: set example vegtables
      elektra:
        mountpoint: /test/example/vegtables
        keys:
          tomato:
              value: ketchup
          potato:
              value: fries

```
