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
  mount:
    description:
      - Specifies a list of files to mount in the KDB
    type: list
    elements: dict
    suboptions:
      mountpoint:
        description:
          - The mountpoint for this file in KDB.
          - 'I.e., user:/myapp'
        required: true
        type: str
      file:
        description:
          - The file which should be mounted.
        required: true
        type: str
      resolver:
        description:
          - The plugin to be used as resolver.
        default: resolver
        type: str
      includeRecommendedPlugins:
        description:
          - If the recommended plugins should also be activated for this mountpoint.
        default: false
        type: bool
      forceRemount:
        description:
          - If the mountpoint should be recreated if it already exists.
        default: false
        type: bool
      preserveKeys:
        description:
          - If the keys below the mountpoint should be preserved if there already are some.
        default: false
        type: bool
      plugins:
        description:
          - A list of plugins that shall be used.
          - You can specify options as dictionary entries.
        required: true
        type: list
        elements: dict
  remove:
    description:
      - A list of keys which should be removed.
      - The list can be a mix of strings (key name) and dictionary (key name is the key, with parameter 'recursive')
      - If you specify the parameter recursive: true, all keys below the key will also be removed.
    type: list
    elements: raw
  keepOrder:
    description:
      - Use "order" metadata to preserve the order of the passed keyset.
      - New keys will be appended after already existing keys in KDB.
      - If a key already exists in KDB, it will keep its existing order.
    type: bool
    required: false
    default: false
  record:
    description:
      - Configuration options for Elektra's session recording feature.
    type: dict
    suboptions:
      enable:
        description:
          - Whether session recording should be enabled after this task is executed.
        type: bool
        default: true
      parentKey:
        description:
          - Changes below this key will be recorded.
        type: str
        default: /
      reset:
        description:
          - Whether the current recording session should be reset.
          - This wil remove all recorded keys from the session.
        type: bool
        default: true
      recordAnsible:
        description:
          - Whether changes to the KDB during the run of this task should be recorded.
        type: bool
        default: false
  merge:
    description:
      - Control how the merging of the given keys with the existing KDB works.
    type: dict
    suboptions:
      strategy:
        description:
          - Which strategy to use to resolve merge conflicts.
          - In a 3-way merge there are 3 keysets: 
          - Ours (the one provided by this task)
          - Theirs (the current configuration)
          - Base (baseline for both)
          - If you select the strategy `ours`, then if there is a conflict, the value provided in this task will be used.
        type: str
        choices:
          - ours
          - theirs
          - abort
        default: ours
      base:
        description:
          - If specified, use the keys defined here as the base keys for the 3-way merge
          - If this is not specified, we will try to determine the base keys based on the current configuration of the host.
          - If changes have been recorded using session recording, the base keys will be the host configuration with those changes undone.
          - Else, the host configuration will also be the base keys.
        type: list
        elements: raw
  keys:
    description:
      - keyset to write
    type: list
    elements: raw

author:
  - Maximilian Irlinger
'''

EXAMPLES = '''
# mount /etc/hosts with recommends to system:/hosts and set localhost to 127.0.0.1
- name: update localhost ip
  elektra:
    mount:
      - mountpoint: system:/hosts
        file: /etc/hosts
        recommends: True
        plugins:
          - hosts:
    keys:
      - system:/hosts:
          ipv4:
            localhost: 127.0.0.1

# mount /tmp/test.ini to system:/testini using the ini plugin and ':' as separator instead of '='
# and replace "key: value" with "key: newvalue"
- name: mount ini
  elektra:
    mount:
      - mountpoint: system:/testini
        file: /tmp/test.ini
        plugins:
          - ini:
              delimiter: ':'
    keys:
     - system:/testini:
         key: newvalue
'''

RETURN = '''
'''

import traceback
from collections import OrderedDict
from subprocess import check_output, CalledProcessError
from typing import List, Tuple

import kdb
import kdb.errors
import kdb.merge
import kdb.record
from ansible.module_utils.basic import AnsibleModule


# import pydevd_pycharm
# pydevd_pycharm.settrace('localhost', port=40671, stdoutToServer=True,  stderrToServer=True)  # The port number here might differ depending on your debug configuration above


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


class ElektraMergeException(ElektraException):
    """There were merge conflicts and ABORT strategy has been specified"""
    def __init__(self, conflicting_keys: kdb.KeySet):
        """
        Create an instance of this exception

        Parameters
        ----------
        conflicting_keys: kdb.KeySet
            KeySet containing all the conflicting keys
        """
        super().__init__(f"There were merge conflicts in the following keys: {conflicting_keys}")
        self.conflicting_keys = conflicting_keys


class RecordingManagerException(ElektraException):
    """Something failed during managing recording"""
    pass


class ElektraTransactionManagerException(Exception):
    """
    Something went wrong with transaction management.
    You probably don't need to catch this exception.
    Just fail the execution.
    There's nothing else you can do.
    """
    pass


class BaseKeysGetter:
    """
    Helper to ease the determination of the base keyset for the 3-way merge.
    """

    def __init__(self, base: kdb.KeySet | None, diff: kdb.ElektraDiff | None):
        """
        Create an instance of BaseKeysGetter.

        Parameters
        ----------
        base: kdb.KeySet or None
            When not `None`, this keyset is used as the base for the 3-way merge.
        diff: kdb.ElektraDiff or None.
            When `base` is `None`, and this is not `None`,
            then we'll use the provided diff to calculate the base keyset.
        """

        self.base = base
        self.diff = diff

    def get_base(self, theirs: kdb.KeySet) -> kdb.KeySet:
        """
        Get the base keyset to be used for the 3-way merge.

        Parameters
        ----------
        theirs: kdb.KeySet
            The keys currently in KDB

        Returns
        -------
        kdb.KeySet
            A keyset suitable to use as the base for the 3-way merge
        """

        if self.base is not None:
            return self.base

        base = deep_dup_keyset(theirs)
        if self.diff is not None:
            self.diff.undo(base)

        return base


class KeyRemover:
    def __init__(self, to_remove: kdb.KeySet | None):
        self.to_remove = to_remove

    def remove_keys(self, keys: kdb.KeySet) -> kdb.KeySet:
        """
        Removes the keys from the keyset.

        Parameters
        ----------
        keys: kdb.KeySet
            The keys will be removed from this keyset

        Returns
        -------
        kdb.KeySet
            The removed keys
        """
        removed_keys = kdb.KeySet(0)
        if self.to_remove is None or len(self.to_remove) == 0:
            return removed_keys

        for key in self.to_remove:
            if key.hasMeta("recursive"):
                removed_keys.append(keys.cut(key))
            else:
                try:
                    removed_keys.append(keys.remove(key.name))
                except ValueError:
                    # Ignore error if key does not exist
                    pass

        return removed_keys


class TransactionManager:
    """
    This is a very basic approach for a transaction.
    Currently, we just store the entire KDB in memory at the beginning of the execution of the Ansible module.
    If a rollback is requested, the whole KDB just gets written back.
    In the future, we could extend the session recording in Elektra to provide full transactional functionality in Elektra
    """

    def __init__(self, is_check_mode: bool):
        """
        Create an instance of the Transaction Manager

        Parameters
        ----------
        is_check_mode: bool
            Whether Ansible is in check mode.
            No changes to the state of KDB will be made if this is `true`
        """
        self.original_configuration: kdb.KeySet | None = None
        self.is_check_mode = is_check_mode
        pass

    def start_transaction(self) -> None:
        """
        Start the transaction.
        We will read the entire KDB and temporarily store it in memory.

        Returns
        -------
        None

        Raises
        ------
        ElektraTransactionManagerException
            If something goes wrong.
        """

        with kdb.KDB() as db:
            ks = kdb.KeySet()
            parent_key = kdb.Key("/")
            rc = db.get(ks, parent_key)
            if rc == -1:
                raise ElektraTransactionManagerException(
                    f"Failed to read initial configuration. {create_text_with_error_and_warnings(parent_key)}")
            self.original_configuration = ks

    def rollback(self) -> None:
        """
        Rollback all changes done to the KDB since the call to `start_transaction`.

        Returns
        -------
        None

        Raises
        ------
        ElektraTransactionManagerException
            If something goes wrong.
        """

        if self.original_configuration is None:
            return

        if self.is_check_mode:
            return

        # We split the rollback in two phases:
        #  - First, rollback the configuration of normal configuration data.
        #    This way, newly created mounted files will be deleted if there was
        #    no configuration for them in the old config.
        #  - Secondly, rollback changes within system:/elektra to also rectify mounts

        original_elektra_keys = self.original_configuration.cut("system:/elektra")

        with kdb.KDB() as db:
            ks = kdb.KeySet()
            parent_key = kdb.Key("/")
            rc = db.get(ks, parent_key)
            if rc == -1:
                raise ElektraTransactionManagerException(
                    f"Failed to read current configuration. {create_text_with_error_and_warnings(parent_key)}")

            # Don't change anything in system:/elektra just now --> append current Elektra config to old configuration
            self.original_configuration.append(ks.cut("system:/elektra"))

            rc = db.set(self.original_configuration, parent_key)
            if rc == -1:
                raise ElektraTransactionManagerException(
                    f"Failed to rollback changes. {create_text_with_error_and_warnings(parent_key)}")

        with kdb.KDB() as db:
            ks = kdb.KeySet()
            parent_key = kdb.Key("system:/elektra")
            rc = db.get(ks, parent_key)
            if rc == -1:
                raise ElektraTransactionManagerException(
                    f"Failed to read system:/elektra. {create_text_with_error_and_warnings(parent_key)}")

            rc = db.set(original_elektra_keys, parent_key)
            if rc == -1:
                raise ElektraTransactionManagerException(
                    f"Failed to rollback changes in system:/elektra. {create_text_with_error_and_warnings(parent_key)}")


class RecordingManager:
    """"
    A simple helper to deal with recording state during the module execution
    """

    def __init__(self, should_reset: bool, should_record_ansible: bool, record_root: kdb.Key | None,
                 is_check_mode: bool):
        """
        Constructor for the Recording Manager.
        For complete initialization, be sure to also call `get_status_quo` too.

        Parameters
        ----------
        should_reset : bool
            whether the current existing session should be reset.
        should_record_ansible: bool
            whether we want to record during the module execution.
        record_root : kdb.Key or None
            if not None, recording below this key will be enabled after module execution.
        is_check_mode : bool
            whether Ansible is in check mode.
            If true, no changes will be made, but we will report if something would change.
        """

        self.is_check_mode = is_check_mode
        self.should_reset = should_reset
        self.should_record_ansible = should_record_ansible
        self.record_root = record_root

        self.changed = False
        self.recording_was_enabled = False
        self.old_recording_parent_key = None
        self.record_contained_keys = False

    def get_status_quo(self) -> List[kdb.errors.ElektraWarning]:
        """
        Gather information about the current state of session recording.

        Returns
        -------
        List[kdb.errors.ElektraWarning]
            A list of warnings issued by KDB.

        Raises
        ------
        RecordingManagerException
            If something goes wrong.
        """

        warnings = []

        with kdb.KDB() as db:
            self.recording_was_enabled = kdb.record.RecordUtil.is_active(db)

        with kdb.KDB() as db:
            error_key = kdb.Key()
            session = kdb.record.RecordUtil.get_diff(db, error_key)
            if session is None:
                raise RecordingManagerException(
                    f"Could not get current recording session. {create_text_with_error_and_warnings(error_key)}")
            self.record_contained_keys = not session.isEmpty()
            warnings.extend(kdb.errors.get_warnings(error_key))

        if self.recording_was_enabled:
            with kdb.KDB() as db:
                ks = kdb.KeySet(0)
                parent_key = kdb.Key("system:/elektra/record/config/active")
                rc = db.get(ks, parent_key)
                if rc == -1:
                    raise RecordingManagerException(
                        f"Could not read active key for recording. {create_text_with_error_and_warnings(parent_key)}")
                self.old_recording_parent_key = ks["system:/elektra/record/config/active"]
                warnings.extend(kdb.errors.get_warnings(parent_key))

        return warnings

    def has_changed(self) -> bool:
        """
        Determine whether state of session recording has been changed.

        Returns
        -------
        bool
            `true` if something as changed, `false` otherwise.
        """

        has_enabled_recording = self.record_root is not None
        if self.recording_was_enabled != has_enabled_recording:
            return True

        old_recording_parent_name = ""
        new_recording_parent_name = ""

        if self.record_root is not None:
            new_recording_parent_name = self.record_root.name

        if self.old_recording_parent_key is not None:
            old_recording_parent_name = self.old_recording_parent_key.value

        if old_recording_parent_name != new_recording_parent_name:
            return True

        if self.record_contained_keys and self.should_reset:
            return True

        # If recordAnsible is enabled we can just return False
        # This is because we already check whether the keys themselves change anything

        return False

    def disable_recording(self) -> List[kdb.errors.ElektraWarning]:
        """
        Disable session recording.

        Returns
        -------
        List[kdb.errors.ElektraWarning]
            A list of warnings issued by KDB.

        Raises
        ------
        RecordingManagerException
            If something goes wrong.
        """

        if self.is_check_mode:
            return []

        with kdb.KDB() as db:
            error_key = kdb.Key()
            successful = kdb.record.RecordUtil.disable(db, error_key)
            if not successful:
                raise RecordingManagerException(
                    f"Disabling recording was not successful. {create_text_with_error_and_warnings(error_key)}")
            return kdb.errors.get_warnings(error_key)

    def reset_recording_session_if_requested(self) -> List[kdb.errors.ElektraWarning]:
        """
        Reset the recording session if this was requested in the playbook.

        Returns
        -------
        List[kdb.errors.ElektraWarning]
            A list of warnings issued by KDB.

        Raises
        ------
        RecordingManagerException
            If something goes wrong.
        """

        if not self.should_reset:
            return []

        with kdb.KDB() as db:
            error_key = kdb.Key()
            successful = kdb.record.RecordUtil.reset(db, error_key)
            if not successful:
                raise RecordingManagerException(
                    f"Clearing recording session was not successful. {create_text_with_error_and_warnings(error_key)}")
            return kdb.errors.get_warnings(error_key)

    @staticmethod
    def _enable_recording(root: kdb.Key) -> Tuple[bool, kdb.Key]:
        error_key = kdb.Key()
        successful = True
        with kdb.KDB() as db:
            successful = kdb.record.RecordUtil.enable(db, root, error_key)

        return successful, error_key

    def enable_recording_for_ansible_if_requested(self) -> List[kdb.errors.ElektraWarning]:
        """
        Enable recording of changes done by this Ansible playbook task if requested.

        Returns
        -------
        List[kdb.errors.ElektraWarning]
            A list of warnings issued by KDB.

        Raises
        ------
        RecordingManagerException
            If something goes wrong.
        """

        if not self.should_record_ansible:
            return []

        successful, error_key = self._enable_recording(kdb.Key("/"))
        if not successful:
            raise RecordingManagerException(
                f"Enabling recording for Ansible was not successful. {create_text_with_error_and_warnings(error_key)}")
        return kdb.errors.get_warnings(error_key)

    def enable_recording_if_requested(self) -> List[kdb.errors.ElektraWarning]:
        """
        Enable recording after Ansible task execution if requested.

        Returns
        -------
        List[kdb.errors.ElektraWarning]
            A list of warnings issued by KDB.

        Raises
        ------
        RecordingManagerException
            If something goes wrong.
        """

        if self.record_root is None:
            return []

        successful, error_key = self._enable_recording(self.record_root)
        if not successful:
            raise RecordingManagerException(
                f"Enabling recording was not successful. {create_text_with_error_and_warnings(error_key)}")
        return kdb.errors.get_warnings(error_key)


def create_text_with_error_and_warnings(error_key: kdb.Key) -> str:
    """
    Create a string that contains the error and all warnings raised in the given key.

    Parameters
    ----------
    error_key: kdb.Key
        The key to gather the error and warnings from.

    Returns
    -------
    str
        String with the error and warnings.
    """

    text = ""
    error = kdb.errors.get_error(error_key)
    if error is not None:
        text = f"Error: {format_elektra_error(error)}\n\n"

    warnings = kdb.errors.get_warnings(error_key)
    for warning in warnings:
        text = f"{text}{format_elektra_error(warning)}\n\n"

    return text.strip()


def format_elektra_error(error: kdb.errors.ElektraError) -> str:
    """
    Create a string that contains all information presented in the given error (or warning)

    Parameters
    ----------
    error: kdb.errors.ElektraError
        The error (or warning) to format.

    Returns
    -------
    str
        Formatted string
    """

    return f"Elektra module {error.module} issued {error.number}: {error.description}: {error.reason}. " \
           f"Mountpoint: {error.mountpoint}, Configfile: {error.configfile}, At: {error.file}, Line: {error.line}"


def flatten_dict(keyset_dict: List[dict], interpret_first_as_namespace=True) -> dict:
    """
    Flattens the given keyset in dict format.
    It will combine the name of the key from a JSON object hierarchy to a flat key name.

    [{
        "user": {
            "test": {
                "myKey": "value",
                "otherKey": [
                    { "value": "value 2" },
                    {
                        "meta": {
                            "elektra": {
                                "deleted": "1"
                            }
                        }
                    }
                ]
            }
        }
    }]

    will become:

    {
        "user:/test/myKey": "value",
        "user:/test/otherKey": {
            "value": "value 2",
            "meta": {
                "elektra/deleted": "1"
            }
        }
    }
    
    Parameters
    ----------
    keyset_dict: dict
        The keyset in dict format

    interpret_first_as_namespace: bool
        Whether the first hierarchy level should be treated as containing the namespace of the key.
        You probably should always use the default value if calling this function from your own code.

    Returns
    -------
    dict
        A keyset in dictionary format with flattened key names.
    """
    out = OrderedDict()

    def ensure_has_object(dictionary, name, ):
        try:
            type(dictionary[name])
        except:
            dictionary[name] = {}

    def flatten(x, name='', root=False):
        if type(x) is dict:
            a: str
            for a in x:
                append_colon = False
                if root and a.find(':') < 0:
                    append_colon = True

                flatten(x[a], f"{name}{a}{':' if append_colon else ''}/")

        elif type(x) is list:
            ensure_has_object(out, name[:-1])
            meta = {}
            element: dict
            for element in x:
                if element.get("value") is not None:
                    out[name[:-1]]['value'] = element.get("value")
                elif element.get("remove") is not None:
                    out[name[:-1]]['remove'] = element.get("remove")
                elif element.get("meta") is not None:
                    meta.update(flatten_dict(element.get("meta"), interpret_first_as_namespace=False))
                elif element.get("keys") is not None:
                    flatten(element.get("keys"), name)
                elif element.get("array") is not None:
                    array_length = 0
                    for array_element in element.get("array"):
                        if type(array_element) is dict and array_element.get("#") is not None:
                            array_element = array_element.get("#")
                        flatten(array_element, f"{name}#{array_length}/")
                        array_length = array_length + 1

                    meta["array"] = f"#{array_length - 1}"
            if len(meta) > 0:
                out[name[:-1]]['meta'] = meta

        else:
            out[name[:-1]] = x

    if type(keyset_dict) is list:
        for element in keyset_dict:
            flatten(element, root=interpret_first_as_namespace)
    elif type(keyset_dict) is dict:
        flatten(keyset_dict, root=interpret_first_as_namespace)

    return out


def build_keyset_from_dict(keyset_dict: List[dict], keep_order: bool) -> kdb.KeySet:
    """
    Build a keyset from a keyset dict.

    Parameters
    ----------
    keyset_dict: List[dict]
        The keyset in dictionary format.
    keep_order: bool
        Whether the metakey `meta:/order` should be generated.

    Returns
    -------
    kdb.Keyset:
        The built keyset
    """

    flattened_keyset = flatten_dict(keyset_dict)

    def build_ks(fk: dict, is_meta=False):
        keyset = kdb.KeySet(0)
        i = 0

        for name, value in fk.items():
            kname = name if not is_meta else f"meta:/{name}"
            key = kdb.Key(kname)
            if keep_order:
                key.setMeta("order", str(i))
                i += 1
            keyset.append(key)

            if isinstance(value, dict):
                for sname, svalue in value.items():
                    if sname == 'value':
                        if key.value != str(svalue):
                            key.value = str(svalue)
                    elif sname == 'remove' and svalue is True:
                        key.setMeta('meta:/elektra/deleted', '1')
                    elif sname == 'meta' and not is_meta:
                        meta_ks = build_ks(svalue, True)
                        for meta_key in meta_ks:
                            key.setMeta(meta_key.name, meta_key.value)
            else:
                if key.value != str(value):
                    key.value = str(value)
        return keyset

    return build_ks(flattened_keyset)


def apply_new_keyset(existing_keys: kdb.KeySet, new_keys: kdb.KeySet, keep_order: bool) -> None:
    """
    "Apply" the keyset defined in the playbook onto the given existing keyset.
    This will make sure that keys marked as deleted in the playbook will be removed.
    It will also ensure the sort order.

    Parameters
    ----------
    existing_keys: kdb.KeySet
        The existing keys.
        This keyset will be directly modified.
    new_keys: kdb.KeySet
        The keys defined in the playbook.
    keep_order: bool
        Whether the `order` meta keys should be updated.

    Returns
    -------
        None
    """

    # Determine the highest order of the exisiting key
    # The new keys will be appended after the existing keys order-wise.
    order_offset = 0
    if keep_order:
        for key in existing_keys:
            if key.hasMeta("order"):
                key_order = int(key.getMeta("order").value)
                order_offset = max(order_offset, key_order)
    order_offset = order_offset + 1

    key: kdb.Key
    for key in new_keys:
        meta_key = key.getMeta("meta:/elektra/deleted")
        if meta_key is not None and (meta_key.value == "1" or meta_key.value == "true"):
            existing_keys.remove(key.name)
        else:
            if keep_order:
                existing_key: kdb.Key | None
                try:
                    existing_key = existing_keys[key.name]
                except:
                    existing_key = None

                if existing_key is not None and existing_key.hasMeta("order"):
                    # If the current key already exist, try to use the existing keys order
                    key.setMeta("order", existing_key.getMeta("order").value)
                elif key.hasMeta("order"):
                    # Order the new keys after all existing keys
                    key_order = int(key.getMeta("order").value)
                    key_order = key_order + order_offset
                    key.setMeta("order", str(key_order))

            existing_keys.append(key)


def deep_dup_keyset(ks: kdb.KeySet) -> kdb.KeySet:
    """
    Creates a deep duplication of the given keyset.

    Parameters
    ----------
    ks: kdb.KeySet
        The keyset to deep-dup.

    Returns
    -------
        A new keyset where all the keys are duplicated from `ks`.
    """

    new = kdb.KeySet(len(ks))
    for key in ks:
        new.append(key)
    return new


def write_keys(keyset: kdb.KeySet,
               base_keys_getter: BaseKeysGetter,
               parent_key: kdb.Key,
               conflict_strategy: kdb.merge.ConflictStrategy,
               key_remover: KeyRemover,
               keep_order: bool,
               is_check_mode: bool) -> Tuple[bool, List[kdb.errors.ElektraWarning]]:
    """
    Write the keyset given in the playbook task to disk.

    Parameters
    ----------
    keyset: kdb.KeySet
        The keys as specified in the playbook task.
    base_keys_getter: BaseKeysGetter
        Helper that provides the base keys for the 3-way merge.
    parent_key: kdb.Key
        The parent key for the whole operation.
    conflict_strategy: kdb.merge.ConflictStrategy
        The strategy to use for resolving merge conflicts
    key_remover: KeyRemover
        Helper that removes the keys specified.
    keep_order:
        Whether the `order` metakeys should be updated.
    is_check_mode:
        Whether Ansible is in check mode.
        If `true`, no changes to the KDB will be performed.

    Returns
    -------
    Tuple[bool, List[kdb.errors.ElektraWarning]]
        The first element of the tuple states whether the state of the KDB changed.
        The second element is a list of warnings generated by KDB.
    """

    warnings = []

    with kdb.KDB() as db:
        theirs = kdb.KeySet(0)
        rc = 0
        try:
            rc = db.get(theirs, parent_key)
            warnings.extend(kdb.errors.get_warnings(parent_key))
        except kdb.KDBException as e:
            raise ElektraReadException("KDB.get failed: {}".format(e))
        if rc == -1:
            raise ElektraReadException(
                f"Failed to read keyset below {parent_key.name}. {create_text_with_error_and_warnings(parent_key)}")

        # Remove the keys that were specified
        # We remove them from theirs, at that forms the base for both "ours" and "base"
        removed_keys = key_remover.remove_keys(theirs)

        base_keys = base_keys_getter.get_base(theirs)
        ours = deep_dup_keyset(theirs)
        apply_new_keyset(ours, keyset, keep_order)

        merger = kdb.merge.Merger()
        merge_result = merger.merge(
            kdb.merge.MergeKeys(base_keys, parent_key.dup()),
            kdb.merge.MergeKeys(ours, parent_key.dup()),
            kdb.merge.MergeKeys(theirs, parent_key.dup()),
            parent_key.dup(),
            conflict_strategy
        )

        warnings.extend(kdb.errors.get_warnings(merge_result.mergeInformation))

        if merge_result.hasConflicts() and conflict_strategy == kdb.merge.ConflictStrategy.ABORT:
            raise ElektraMergeException(merge_result.getConflictingKeys(parent_key))

        merge_error = kdb.errors.get_error(merge_result.mergeInformation)
        if merge_error is not None:
            raise ElektraException(
                f"Error merging keys. {create_text_with_error_and_warnings(merge_result.mergeInformation)}")

        keys_to_save = merge_result.mergedKeys

        diff: kdb.ElektraDiff = db.calculateChanges(keys_to_save, parent_key)
        if diff.isEmpty() and len(removed_keys) == 0:
            # No changes to the KDB are necessary
            return False, warnings

        if is_check_mode:
            # Check mode is active, don't persist changes to KDB
            # As we arrived here, there are changes, so return True to indicate this
            return True, warnings

        try:
            rc = db.set(keys_to_save, parent_key)
            warnings.extend(kdb.errors.get_warnings(parent_key))
        except kdb.KDBException as e:
            raise ElektraWriteException("KDB.set failed: {}".format(e))
        if rc == -1:
            raise ElektraWriteException(
                f"Failed to write keyset to {parent_key.name}. {create_text_with_error_and_warnings(parent_key)}")

        if rc == 1:
            return True, warnings
        return False, warnings


def execute(command: List[str]) -> Tuple[int, str]:
    """
    Executes the given command.

    Parameters
    ----------
    command: List[str]
        A command in list notation.
        The first element of the list is the command to run.
        All other elements are treated as command-line arguments.

    Returns
    -------
    Tuple[int, str]
        The first element of the tuple is the return code.
        The second element is the command-line output.
    """
    try:
        output = check_output(command)
        return (0, output)
    except CalledProcessError as e:
        return (e.returncode, e.output)


def execute_elektra_mount(mountpoint: str,
                          filename: str,
                          resolver: str,
                          plugins: List[dict],
                          recommends: bool) -> Tuple[int, str]:
    """
    Executes the `kdb mount` command.

    Parameters
    ----------
    mountpoint: str
        The path of the Elektra mountpoint.
        E.g., system:/myapp
    filename: str
        The path to the file that shall be mounted.
    resolver: str
        The name of the resolver plugin to use.
    plugins: List[dict]
        A list of plugins.
        A "plugin" is a dict where the top-level item in the dict is the name of the plugin.
        The dict below the top-level item is treated as the configuration of the plugin.
        [
            {
                my_plugin: {
                    my_param: param_value.
                }
            }
        ]
    recommends: bool
        Whether recommended plugins should be loaded.

    Returns
    -------
    Tuple[int, str]
        The first element of the tuple is the return code of the `kdb mount` command.
        The second element is the command-line output.
    """

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
            command.append(str(cname))  # plugin
            if isinstance(cvalue, dict):  # iterate plugin meta
                for scname, scvalue in cvalue.items():
                    command.append(str(scname) + "=" + str(scvalue))
    return execute(command)


def elektra_unmount(mountpoint: str) -> None:
    """
    Unmount the specified Elektra mountpoint.

    Parameters
    ----------
    mountpoint: str
        Name of the mountpoint.
        E.g, system:/myapp.

    Returns
    -------
    None

    Raises
    ------
    ElektraReadException
        If reading from KDB failed.

    ElektraWriteException
        If writing to KDB failed.

    ElektraUmountException
        If something else went wrong.
    """

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
        key.name = mountpoints + '/' + mountpoint.replace('/', '\\/')
        ks.cut(key)
        try:
            rc = db.set(ks, mountpoints)
        except kdb.KDBException as e:
            raise ElektraWriteException("KDB.set failed: {}".format(e))
        if rc != 1:
            raise ElektraUmountException("Failed to umount " + key.name)


def handle_mounts(mount_options: List[dict] | None, is_check_mode: bool) \
        -> Tuple[bool, List[kdb.errors.ElektraWarning]]:
    """
    Handle the mounting of the mountpoints specified in the playbook.

    Parameters
    ----------
    mount_options: List[dict] or None
        The mount options as specified in the playbook task.
    is_check_mode: bool
        Whether Ansible is in check mode.
        If `true`, no changes will be performed to the KDB.

    Returns
    -------
    Tuple[bool, List[kdb.errors.ElektraWarning]]
        The first element of the tuple is a bool indicating whether state has changed.
        The second element is a list of warnings issued by KDB.

    Raises
    ------
    ElektraMountException
        If something went wrong.
    """

    changed = False
    warnings = []

    if mount_options is None:
        return changed, warnings

    ks = kdb.KeySet()
    with kdb.KDB() as db:
        parent_key = kdb.Key("system:/elektra/mountpoints")
        rc = db.get(ks, parent_key)
        if rc == -1:
            raise ElektraMountException(
                f"Could not get existing mountpoints. {create_text_with_error_and_warnings(parent_key)}")
        warnings.extend(kdb.errors.get_warnings(parent_key))

    def does_mountpoint_exist(name):
        search_key = 'system:/elektra/mountpoints/' + name.replace('/', '\\/')
        try:
            _ = ks[search_key]
            return True
        except KeyError:
            return False

    for mount_point_definition in mount_options:
        name = mount_point_definition.get('mountpoint')
        file_name = mount_point_definition.get('file')
        resolver = mount_point_definition.get('resolver')
        recommends = mount_point_definition.get('includeRecommendedPlugins')
        plugins = mount_point_definition.get('plugins')
        force_remount = mount_point_definition.get('forceRemount')
        preserve_keys = mount_point_definition.get('preserveKeys')

        does_exist = does_mountpoint_exist(name)

        if does_exist and not force_remount:
            continue

        changed = True

        if is_check_mode:
            break

        saved_keys = None
        if preserve_keys:
            saved_keys = kdb.KeySet(0)
            parent_key = kdb.Key(name)
            with kdb.KDB() as db:
                rc = db.get(saved_keys, parent_key)
                if rc == -1:
                    raise ElektraMountException(
                        f"Could not read keys below {name}. {create_text_with_error_and_warnings(parent_key)}")
                warnings.extend(kdb.errors.get_warnings(parent_key))

        if does_exist:
            elektra_unmount(name)

        if plugins is None:
            plugins = [{"dump": {}}]

        rc, command_output = execute_elektra_mount(name, file_name, resolver, plugins, recommends)
        if rc != 0:
            raise ElektraMountException(
                f"Could not mount mountpoint {name} for file {file_name}: {command_output}")

        if saved_keys is not None and len(saved_keys) > 0:
            parent_key = kdb.Key(name)
            with kdb.KDB() as db:
                tmp = kdb.KeySet(0)
                rc = db.get(tmp, parent_key)
                if rc == -1:
                    raise ElektraMountException(
                        f"Could not read keys below {name}. {create_text_with_error_and_warnings(parent_key)}")
                warnings.extend(kdb.errors.get_warnings(parent_key))

                rc = db.set(saved_keys, parent_key)
                if rc == -1:
                    raise ElektraMountException(
                        f"Could not write keys below {name}. {create_text_with_error_and_warnings(parent_key)}")
                warnings.extend(kdb.errors.get_warnings(parent_key))

    return changed, warnings


def parse_merge_options(merge_options: dict | None) \
        -> Tuple[BaseKeysGetter, kdb.merge.ConflictStrategy, List[kdb.errors.ElektraWarning]]:
    """
    Parses the merge options specified in the playbook.

    Parameters
    ----------
    merge_options: dict or None
        The merge options as specified in the playbook.

    Returns
    -------
    Tuple[BaseKeysGetter, kdb.merge.ConflictStrategy, List[kdb.errors.ElektraWarning]]
        The first element of the tuple is the `BaseKeysGetter`.
        The second element is the merge strategy to use.
        The third element is the list of warnings issued by KDB.

    Raises
    ------
    ElektraException
        If something went wrong.
    """

    base_keys_getter = BaseKeysGetter(None, None)
    conflict_strategy = kdb.merge.ConflictStrategy.OUR
    warnings = []

    if merge_options is None:
        return base_keys_getter, conflict_strategy, warnings

    strat: str = merge_options.get('strategy')
    if strat.lower().startswith("their"):
        conflict_strategy = kdb.merge.ConflictStrategy.THEIR
    elif strat.lower().startswith("our"):
        conflict_strategy = kdb.merge.ConflictStrategy.OUR
    elif strat.lower().startswith("abort"):
        conflict_strategy = kdb.merge.ConflictStrategy.ABORT

    if merge_options.get('base') is not None:
        base_keys = build_keyset_from_dict(merge_options.get('base'), False)
        base_keys_getter = BaseKeysGetter(base_keys, None)
    else:
        with kdb.KDB() as db:
            error_key = kdb.Key()
            diff = kdb.record.RecordUtil.get_diff(db, error_key)
            if diff is None:
                raise ElektraException(
                    f"Failed to get current recording session diff. {create_text_with_error_and_warnings(error_key)}")
            base_keys_getter = BaseKeysGetter(None, diff)
            warnings = kdb.errors.get_warnings(error_key)

    return base_keys_getter, conflict_strategy, warnings


def parse_record_options(record_options: dict | None, is_check_mode: bool) -> RecordingManager:
    """
    Parse the record options in the playbook and build a `RecordingManager`.

    Parameters
    ----------
    record_options: dict or None
        The recording options as specified in the playbook.

    is_check_mode: bool.
        Whether Ansible is in check mode.

    Returns
    -------
    RecordingManager
        The recording manager.
    """

    should_reset = True
    should_record_ansible = False
    record_root = kdb.Key("/")

    if record_options is not None:
        should_reset = record_options.get('reset')
        should_record_ansible = record_options.get('recordAnsible')
        if record_options.get('enable'):
            rr = record_options.get('parentKey')
            record_root = kdb.Key(rr)
        else:
            record_root = None

    return RecordingManager(should_reset, should_record_ansible, record_root, is_check_mode)


def parse_keys_to_remove(remove_options: List[dict] | None) -> KeyRemover:
    """
    Parse the remove options specified in the playbook.

    Parameters
    ----------
    remove_options: dict or None
        The options as specified in the playbook.

    Returns
    -------
    KeyRemover
        The keyremover that will remove the specified keys.
    """
    ks = kdb.KeySet(0)
    if remove_options is None:
        return KeyRemover(ks)

    for k in remove_options:
        key: kdb.Key
        is_recursive = False

        if isinstance(k, dict):
            options: dict
            name, options = list(k.items())[0]
            key = kdb.Key(name)
            is_recursive = options.get("recursive", False)
        elif isinstance(k, str):
            key = kdb.Key(k)
        else:
            raise ElektraException(f"Options for 'remove' have no valid format. Offending option: {k}")

        if is_recursive:
            key.setMeta("recursive", "true")

        ks.append(key)

    return KeyRemover(ks)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            mount=dict(
                type='list',
                elements='dict',
                options=dict(
                    mountpoint=dict(type='str', required=True),
                    file=dict(type='str', required=True),
                    resolver=dict(type='str', default='resolver'),
                    plugins=dict(type='list', elements='dict'),
                    includeRecommendedPlugins=dict(type='bool', default=True),
                    forceRemount=dict(type='bool', default=False),
                    preserveKeys=dict(type='bool', default=False),
                )
            ),
            remove=dict(
                type='list',
                elements='raw',
            ),
            keepOrder=dict(type='bool', default=False),
            record=dict(
                type='dict',
                options=dict(
                    enable=dict(type='bool', default=True),
                    parentKey=dict(type='str', default='/'),
                    reset=dict(type='bool', default=True),
                    recordAnsible=dict(type='bool', default=False)
                )
            ),
            merge=dict(
                type='dict',
                options=dict(
                    strategy=dict(type='str', default='ours', choices=['ours', 'theirs', 'abort']),
                    base=dict(
                        type='list',
                        elements='raw',
                        required=False
                    )
                )
            ),
            keys=dict(
                type='list',
                elements='raw'
            )
        ),
        supports_check_mode=True
    )

    json_output = {'changed': False}
    changed = False

    transaction_manager = TransactionManager(module.check_mode)
    transaction_manager.start_transaction()

    try:
        # Build record information
        recording_manager = parse_record_options(module.params.get('record'), module.check_mode)

        # Save status quo for changed information
        warnings = recording_manager.get_status_quo()
        for warning in warnings:
            module.warn(format_elektra_error(warning))

        # Disable session recording
        warnings = recording_manager.disable_recording()
        for warning in warnings:
            module.warn(format_elektra_error(warning))

        # Build merge information. We may need session recording storage for this
        base_keys_getter, conflict_strategy, warnings = parse_merge_options(module.params.get('merge'))
        for warning in warnings:
            module.warn(format_elektra_error(warning))

        # Reset session recording if requested
        warnings = recording_manager.reset_recording_session_if_requested()
        for warning in warnings:
            module.warn(format_elektra_error(warning))

        # Handle mounts
        mount_changed, warnings = handle_mounts(module.params.get('mount'), module.check_mode)
        for warning in warnings:
            module.warn(format_elektra_error(warning))
        changed = changed or mount_changed

        # Enable session recording for ansible if requested
        warnings = recording_manager.enable_recording_for_ansible_if_requested()
        for warning in warnings:
            module.warn(format_elektra_error(warning))

        # Get and build keys
        keep_order: bool = module.params.get('keepOrder')
        keys = build_keyset_from_dict(module.params.get('keys'), keep_order)

        # Get which key hierarchies should be removed
        key_remover = parse_keys_to_remove(module.params.get('remove'))

        # Merge and write keys to KDB
        write_changed, warnings = write_keys(keys,
                                             base_keys_getter,
                                             kdb.Key("/"),
                                             conflict_strategy,
                                             key_remover,
                                             keep_order,
                                             module.check_mode)
        for warning in warnings:
            module.warn(format_elektra_error(warning))
        changed = changed or write_changed

        # Disable session recording again (may have been enabled for ansible)
        warnings = recording_manager.disable_recording()
        for warning in warnings:
            module.warn(format_elektra_error(warning))

        # Enable session recording if requested
        warnings = recording_manager.enable_recording_if_requested()
        for warning in warnings:
            module.warn(format_elektra_error(warning))
        changed = changed or recording_manager.has_changed()

    except Exception as e:
        transaction_manager.rollback()
        module.fail_json(msg=f"{e} {traceback.format_exception(e)}")

    json_output['changed'] = changed
    module.exit_json(**json_output)


if __name__ == '__main__':
    main()
