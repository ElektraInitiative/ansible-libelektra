# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import kdb
from ansible_collections.elektra_initiative.libelektra.plugins.modules.elektra import (
    apply_new_keyset, flatten_dict, build_keyset_from_dict, parse_keys_to_remove, KeyRemover
)


def test__apply_new_keyset__empty_keysets__should_work():
    # Arrange
    newKs = kdb.KeySet(0)
    existingKs = kdb.KeySet(0)

    # Act
    apply_new_keyset(existingKs, newKs, False)

    # Assert
    assert len(existingKs) == 0


def test__apply_new_keyset__should_combine():
    # Arrange
    newKs = kdb.KeySet(0)
    newKs.append(kdb.Key("user:/hello/world", "max"))
    existingKs = kdb.KeySet(0)
    existingKs.append((kdb.Key("system:/test", "123")))

    # Act
    apply_new_keyset(existingKs, newKs, False)

    # Assert
    assert len(existingKs) == 2
    assert existingKs["user:/hello/world"] is not None
    assert existingKs["system:/test"] is not None


def test__apply_new_keyset__with_deleted_meta__should_delete():
    # Arrange
    existingKs = kdb.KeySet(0)
    existingKs.append((kdb.Key("system:/test", "123")))
    existingKs.append(kdb.Key("system:/hello", "max"))

    newKs = kdb.KeySet(0)
    keyToDelete = kdb.Key("system:/hello", "someValue")
    keyToDelete.setMeta("meta:/elektra/removed", "1")
    newKs.append(keyToDelete)

    # Act
    apply_new_keyset(existingKs, newKs, False)

    # Assert
    assert len(existingKs) == 1
    assert existingKs["system:/test"] is not None


def test_apply_new_keyset__should_keep_order():
    # Arrange
    existing_ks = kdb.KeySet(0)

    k = kdb.Key("user:/test/k1", "1")
    k.setMeta("order", "2")
    existing_ks.append(k)

    k = kdb.Key("user:/test/k2", "2")
    k.setMeta("order", "1")
    existing_ks.append(k)

    k = kdb.Key("user:/test/k3", "3")
    k.setMeta("order", "0")
    existing_ks.append(k)

    new_ks = kdb.KeySet(0)

    k = kdb.Key("user:/test/k2", "n2")
    k.setMeta("order", "1")
    new_ks.append(k)

    k = kdb.Key("user:/test/k4", "4")
    k.setMeta("order", "2")
    new_ks.append(k)

    k = kdb.Key("user:/test/k5", "5")
    k.setMeta("order", "0")
    new_ks.append(k)

    # Act
    apply_new_keyset(existing_ks, new_ks, True)

    # Assert
    assert len(existing_ks) == 5
    assert existing_ks["user:/test/k3"].getMeta("order").value == "0"
    assert existing_ks["user:/test/k2"].getMeta("order").value == "1"
    assert existing_ks["user:/test/k1"].getMeta("order").value == "2"
    assert existing_ks["user:/test/k5"].getMeta("order").value == "3"
    assert existing_ks["user:/test/k4"].getMeta("order").value == "5"


def test__flatten_dict__should_flatten():
    # Arrange
    keys = [
        {
            "user:/hosts": {
                "localhost": {
                    "ipv4": [
                        {
                            "value": "127.0.0.1"
                        },
                        {
                            "meta": {
                                "elektra": {
                                    "test": "1"
                                }
                            }
                        },
                    ],
                    "ipv6": [
                        {
                            "value": "::1"
                        }
                    ]
                },
                "example.com": {
                    "ipv4": [
                        {
                            "value": "1.2.3.4"
                        }
                    ]
                }
            },
            "system": {
                "drink": [
                    {"value": "beer"},
                    {"meta": {
                        "healthy": "false"
                    }
                    }
                ],
                "cake": "lie",
                "nonleaf": [
                    {"value": "non-leaf value"},
                    {
                        "keys": {
                            "further": {
                                "continuation": "123"
                            },
                            "raspberry": "pie"
                        }
                    }
                ]
            },
            "dir:/animals": [
                {
                    "array": [
                        {
                            "species": "cow",
                            "name": "Bessie",
                        },
                        {
                            "#": [
                                {
                                    "meta": {
                                        "goodboy": "true"
                                    }
                                },
                                {
                                    "keys": {
                                        "species": "dog",
                                        "name": "Rufus"
                                    }
                                }
                            ]
                        },
                        "value of 3rd element",
                        {
                            "#": "value of 4th element"
                        }
                    ]
                },
                {
                    "meta": {
                        "something": "abc"
                    }
                }
            ],
        }
    ]

    # Act
    flattened = flatten_dict(keys)

    # Assert
    assert len(flattened) == 16
    assert flattened["user:/hosts/localhost/ipv4"] is not None
    assert flattened["user:/hosts/localhost/ipv4"]["value"] == "127.0.0.1"
    assert flattened["user:/hosts/localhost/ipv4"]["meta"] is not None
    assert flattened["user:/hosts/localhost/ipv4"]["meta"]["elektra/test"] == "1"
    assert flattened["user:/hosts/localhost/ipv6"] is not None
    assert flattened["user:/hosts/localhost/ipv6"]["value"] == "::1"
    assert flattened["user:/hosts/example.com/ipv4"] is not None
    assert flattened["user:/hosts/example.com/ipv4"]["value"] == "1.2.3.4"
    assert flattened["system:/drink"] is not None
    assert flattened["system:/drink"]["value"] == "beer"
    assert flattened["system:/drink"]["meta"] is not None
    assert flattened["system:/drink"]["meta"]["healthy"] == "false"
    assert flattened["system:/cake"] is not None
    assert flattened["system:/cake"] == "lie"
    assert flattened["system:/nonleaf"] is not None
    assert flattened["system:/nonleaf"]["value"] == "non-leaf value"
    assert flattened["system:/nonleaf/further/continuation"] is not None
    assert flattened["system:/nonleaf/further/continuation"] == "123"
    assert flattened["system:/nonleaf/raspberry"] is not None
    assert flattened["system:/nonleaf/raspberry"] == "pie"
    assert flattened["dir:/animals"] is not None
    assert flattened["dir:/animals"]["meta"] is not None
    assert flattened["dir:/animals"]["meta"]["array"] == "#3"
    assert flattened["dir:/animals"]["meta"]["something"] == "abc"
    assert flattened["dir:/animals/#0/species"] is not None
    assert flattened["dir:/animals/#0/species"] == "cow"
    assert flattened["dir:/animals/#0/name"] is not None
    assert flattened["dir:/animals/#0/name"] == "Bessie"
    assert flattened["dir:/animals/#1"] is not None
    assert flattened["dir:/animals/#1"]["meta"] is not None
    assert flattened["dir:/animals/#1"]["meta"]["goodboy"] == "true"
    assert flattened["dir:/animals/#1/species"] is not None
    assert flattened["dir:/animals/#1/species"] == "dog"
    assert flattened["dir:/animals/#1/name"] is not None
    assert flattened["dir:/animals/#1/name"] == "Rufus"
    assert flattened["dir:/animals/#2"] is not None
    assert flattened["dir:/animals/#2"] == "value of 3rd element"
    assert flattened["dir:/animals/#3"] is not None
    assert flattened["dir:/animals/#3"] == "value of 4th element"


def test__flatten_dict__should_flatten_meta():
    # Arrange
    keys = [
        {
            "user:/test": {
                "raspberry": [
                    {"value": "pie"},
                    {"meta": {
                        "comment": {
                            "#1": [
                                {"value": "this is my comment"},
                                {"keys": {
                                    "space": "Nothing",
                                    "start": [
                                        {"value": "#"}
                                    ]
                                }}
                            ]
                        }
                    }}
                ]
            }
        }
    ]

    # Act
    result = flatten_dict(keys)

    # Assert
    assert len(result) == 1
    assert result["user:/test/raspberry"] is not None
    assert result["user:/test/raspberry"]["value"] == "pie"
    assert result["user:/test/raspberry"]["meta"] is not None
    assert len(result["user:/test/raspberry"]["meta"]) == 3
    assert result["user:/test/raspberry"]["meta"]["comment/#1"] is not None
    assert result["user:/test/raspberry"]["meta"]["comment/#1"]["value"] == "this is my comment"
    assert result["user:/test/raspberry"]["meta"]["comment/#1/space"] is not None
    assert result["user:/test/raspberry"]["meta"]["comment/#1/space"] == "Nothing"
    assert result["user:/test/raspberry"]["meta"]["comment/#1/start"] is not None
    assert result["user:/test/raspberry"]["meta"]["comment/#1/start"]["value"] == "#"


def test__build_keyset_from_dict__no_keep_order__should_work():
    # Arrange
    keys = [
        {
            "user:/hosts": {
                "localhost": {
                    "ipv4": [
                        {
                            "value": "127.0.0.1"
                        },
                        {
                            "meta": {
                                "elektra": {
                                    "test": "1"
                                }
                            }
                        },
                    ],
                    "ipv6": [
                        {
                            "value": "::1"
                        }
                    ]
                },
                "example.com": {
                    "ipv4": [
                        {
                            "value": "1.2.3.4"
                        },
                        {
                            "remove": True
                        }
                    ]
                }
            },
            "system": {
                "drink": [
                    {"value": "beer"},
                    {"meta": {
                        "healthy": "false"
                    }
                    }
                ],
                "cake": "lie",
                "nonleaf": [
                    {"value": "non-leaf value"},
                    {
                        "keys": {
                            "further": {
                                "continuation": "123"
                            },
                            "raspberry": "pie"
                        }
                    }
                ]
            },
            "dir:/animals": [
                {
                    "array": [
                        {
                            "species": "cow",
                            "name": "Bessie",
                        },
                        {
                            "#": [
                                {
                                    "meta": {
                                        "goodboy": "true"
                                    }
                                },
                                {
                                    "keys": {
                                        "species": "dog",
                                        "name": "Rufus"
                                    }
                                }
                            ]
                        },
                        "value of 3rd element",
                        {
                            "#": "value of 4th element"
                        }
                    ]
                },
                {
                    "meta": {
                        "something": "abc"
                    }
                }
            ],
        }
    ]

    # Act
    ks = build_keyset_from_dict(keys, False)

    # Assert
    assert ks is not None
    assert len(ks) == 16
    assert ks["user:/hosts/localhost/ipv4"] is not None
    assert ks["user:/hosts/localhost/ipv4"].value == "127.0.0.1"
    assert ks["user:/hosts/localhost/ipv4"].getMeta("meta:/elektra/test") is not None
    assert ks["user:/hosts/localhost/ipv4"].getMeta("meta:/elektra/test").value == "1"
    assert ks["user:/hosts/example.com/ipv4"] is not None
    assert ks["user:/hosts/example.com/ipv4"].value == "1.2.3.4"

    # the 'remove' marker should add the meta:/elektra/removed meta data
    assert ks["user:/hosts/example.com/ipv4"].getMeta("meta:/elektra/removed") is not None
    assert ks["user:/hosts/example.com/ipv4"].getMeta("meta:/elektra/removed").value == "1"

    assert ks["system:/drink"] is not None
    assert ks["system:/drink"].value == "beer"
    assert ks["system:/drink"].getMeta("meta:/healthy").value == "false"
    assert ks["system:/cake"] is not None
    assert ks["system:/cake"].value == "lie"
    assert ks["system:/nonleaf"] is not None
    assert ks["system:/nonleaf"].value == "non-leaf value"
    assert ks["system:/nonleaf/further/continuation"] is not None
    assert ks["system:/nonleaf/further/continuation"].value == "123"
    assert ks["system:/nonleaf/raspberry"] is not None
    assert ks["system:/nonleaf/raspberry"].value == "pie"
    assert ks["dir:/animals"] is not None
    assert ks["dir:/animals"].getMeta("meta:/array").value == "#3"
    assert ks["dir:/animals"].getMeta("meta:/something").value == "abc"
    assert ks["dir:/animals/#0/species"] is not None
    assert ks["dir:/animals/#0/species"].value == "cow"
    assert ks["dir:/animals/#0/name"] is not None
    assert ks["dir:/animals/#0/name"].value == "Bessie"
    assert ks["dir:/animals/#1"] is not None
    assert ks["dir:/animals/#1"].getMeta("goodboy").value == "true"
    assert ks["dir:/animals/#1/species"] is not None
    assert ks["dir:/animals/#1/species"].value == "dog"
    assert ks["dir:/animals/#1/name"] is not None
    assert ks["dir:/animals/#1/name"].value == "Rufus"
    assert ks["dir:/animals/#2"] is not None
    assert ks["dir:/animals/#2"].value == "value of 3rd element"
    assert ks["dir:/animals/#3"] is not None
    assert ks["dir:/animals/#3"].value == "value of 4th element"


def test__build_keyset_from_dict__should_flatten_meta():
    # Arrange
    keys = [
        {
            "user:/test": {
                "raspberry": [
                    {"value": "pie"},
                    {"meta": {
                        "comment": {
                            "#1": [
                                {"value": "this is my comment"},
                                {"keys": {
                                    "space": "Nothing",
                                    "start": [
                                        {"value": "#"}
                                    ]
                                }}
                            ]
                        }
                    }}
                ]
            }
        }
    ]

    # Act
    result = build_keyset_from_dict(keys, False)

    # Assert
    assert len(result) == 1
    assert result["user:/test/raspberry"] is not None
    assert result["user:/test/raspberry"].value == "pie"
    assert result["user:/test/raspberry"].getMeta() is not None
    assert result["user:/test/raspberry"].getMeta("meta:/comment/#1") is not None
    assert result["user:/test/raspberry"].getMeta("meta:/comment/#1").value == "this is my comment"
    assert result["user:/test/raspberry"].getMeta("meta:/comment/#1/space") is not None
    assert result["user:/test/raspberry"].getMeta("meta:/comment/#1/space").value == "Nothing"
    assert result["user:/test/raspberry"].getMeta("comment/#1/start") is not None
    assert result["user:/test/raspberry"].getMeta("comment/#1/start").value == "#"


def test__parse_keys_to_remove__should_correctly_parse():
    # Arrange
    argument = [
        "user:/",
        {"spec:/": {"something": "else"}},
        {"dir:/": {"recursive": True}}
    ]

    # Act
    key_remover = parse_keys_to_remove(argument)

    # Assert
    assert len(key_remover.to_remove) == 3
    assert not key_remover.to_remove["user:/"].hasMeta("recursive")
    assert not key_remover.to_remove["spec:/"].hasMeta("recursive")
    assert key_remover.to_remove["dir:/"].hasMeta("recursive")


def test__key_remove__should_remove_keys():
    # Arrange
    keys = kdb.KeySet(0)
    keys.append(kdb.Key("user:/test"))
    keys.append(kdb.Key("user:/test/1"))
    keys.append(kdb.Key("user:/test/2"))
    keys.append(kdb.Key("user:/else"))
    keys.append(kdb.Key("user:/else/1"))
    keys.append(kdb.Key("user:/else/2"))
    keys.append(kdb.Key("user:/nice"))

    to_remove = kdb.KeySet()
    to_remove.append(kdb.Key("user:/else"))
    rec_key = kdb.Key("user:/test")
    rec_key.setMeta("recursive", "true")
    to_remove.append(rec_key)

    key_remover = KeyRemover(to_remove)

    # Act
    removed = key_remover.remove_keys(keys)

    # Assert
    assert len(removed) == 4
    assert removed["user:/test"] is not None
    assert removed["user:/test/1"] is not None
    assert removed["user:/test/2"] is not None
    assert removed["user:/else"] is not None

    assert len(keys) == 3
    assert keys["user:/else/1"] is not None
    assert keys["user:/else/2"] is not None
    assert keys["user:/nice"] is not None
