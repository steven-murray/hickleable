"""A package defining convenience functions for hickle.

The primary function defined is :func:`hickleable`, a decorator to put on top of classes
that usually magically makes them hickle-able (without resorting to pickling).
"""
from __future__ import annotations

import hickle
import inspect
import warnings
from functools import cached_property
from h5py import AttributeManager, Group
from hickle.lookup import LoaderManager, PyContainer
from pathlib import Path
from typing import Any, Callable, Iterable, List, Tuple

DumpOutput = Tuple[Group, List[Tuple[str, Any, dict, dict]]]
DumpFunctionType = Callable[[Any, Group, str], DumpOutput]

try:
    import yaml
except ImportError:
    yaml = None


def hickleable(
    hkl_str: bytes | None = None,
    dump_function: None | DumpFunctionType = None,
    load_container: None | Callable[[Any], PyContainer] | PyContainer = None,
    metadata_keys: Iterable[str] | None = None,
    evaluate_cached_properties: bool = False,
    **kwargs,
):
    """Make a class dumpable/loadable by hickle, with sane defaults.

    By adding this function decorator to your custom class, the class will be instantly
    writeable to HDF5 file. By default, all attributes of the object are saved to the
    HDF5 file. Those that have types already supported by hickle (eg. builtins, numpy,
    scipy and astropy) will natively be written to file, and any attribute that is
    itself decorated with this decorator. Other attributes will be saved in binary
    pickle format inside the file.

    The easiest way to customize writing and loading of files is to use a
    ``__gethstate__`` and ``__sethstate__`` methods on your class. The ``__gethstate__``
    method should return a dictionary that has all the state of the class in it.
    By default, this function uses the ``__getstate__`` method if ``__gethstate__`` does
    not exist, and if that doesn't exist either, it will simply use the ``__dict__``
    attribute. Similarly, ``__sethstate__`` should be reverse -- it should accept a dict
    of state, and update the object instance's ``__dict__`` attribute to set the state.
    If not present, ``__setstate__`` will be used.


    Parameters
    ----------
    hkl_str
        A name representing the group under which the object will be stored in the h5
        file. By default, it is the ``module.class_name`` of the class being
        decorated.
    dump_function
        A callable with the signature
        ``dump_function(py_obj: Any, h_group: Group, name: str)``. The ``py_obj`` will
        be an instance of the class being decorated. The h_group will be a reference
        to a HDF5 Group into which it will be written. The ``name`` will be the name
        of the sub-group into which the object is written. The return value should be
        a Dataset or Group into which the object has been written, as well as a list
        of tuples of sub-items. To be stored. If the first output is a Dataset,
        no sub-items should be returned.
    load_container
        Either a function taking the decorated class and returning a
        :class:`hickle.PyContainer`, or a :class:`hickle.PyContainer` class itself.
        See documentation for the :class:`hickle.PyContainer`. By default, this will use
        either ``__sethstate__ `` or ``__setstate__`` to construct the class object.
        Additionally, if the object is an ``attrs`` object, it will call the post-init
        step.
    metadata_keys
        Any element of the object's state that should be treated as metadata, to be
        stored in the file's ``attrs`` dictionary instead of in datasets/subgroups
    evaluate_cached_properties
        Whether to force any cached properties to be evaluated before writing, so that
        when reading they are pre-cached.
    """

    def inner(cls: type):
        """The wrapper function for the custom class."""
        if hkl_str is None:
            hstr = f"!{cls.__module__}.{cls.__name__}!".encode()
        elif isinstance(hkl_str, str):
            hstr = hkl_str.encode()
        elif isinstance(hkl_str, bytes):
            hstr = hkl_str
        else:
            raise TypeError(
                "hkl_str must be a string or bytes. "
                f"Got {hkl_str} with type {type(hkl_str)}."
            )

        if dump_function is None:

            def _dump_function(py_obj, h_group, name, **kwargs):
                ds = h_group.create_group(name)

                if evaluate_cached_properties:
                    all_cached_properties = [
                        name
                        for name, value in inspect.getmembers(py_obj.__class__)
                        if isinstance(value, cached_property)
                    ]
                    for cp in all_cached_properties:
                        getattr(py_obj, cp)

                if hasattr(py_obj, "__gethstate__"):
                    state = py_obj.__gethstate__()
                elif hasattr(py_obj, "__getstate__"):
                    state = py_obj.__getstate__()
                else:
                    state = py_obj.__dict__

                for k in metadata_keys or []:
                    if k in state:
                        ds.attrs[k] = state.pop(k)
                    else:
                        warnings.warn(
                            f"Ignoring metadata key {k} since it's not in the object.",
                            stacklevel=2,
                        )

                subitems = []
                for k, v in state.items():
                    subitems.append((k, v, {}, kwargs))

                return ds, subitems

        else:
            _dump_function = dump_function  # pragma: no cover

        if load_container is None:

            class _load_container(PyContainer):  # noqa: N801
                def __init__(self, h5_attrs: dict, base_type: str, object_type: Any):
                    """The load container.

                    Parameters
                    ----------
                    h5_attrs
                        the attrs dictionary attached to the group representing the
                        custom class.
                    base_type
                        byte string naming the loader to be used for restoring the
                        custom class object
                    py_obj_type
                        Custom class (or subclass)
                    """
                    # the optional protected _content parameter of the PyContainer
                    # __init__ method can be used to change the data structure used to
                    # store the subitems passed to the append method of the PyContainer
                    # class per default it is set to []
                    super().__init__(
                        h5_attrs, base_type, object_type, _content=dict(h5_attrs)
                    )

                def append(self, name: str, item: Any, h5_attrs: AttributeManager):
                    """Add a particular item to the content defining the object.

                    Parameters
                    ----------
                    name
                        Identifies the subitem within the parent ``hdf5.Group``
                    item
                        The object representing the subitem
                    h5_attrs
                        An ``attrs`` dictionary attached to the ``h5py.Dataset`` or
                        ``h5py.Group`` representing the item.
                    """
                    self._content[name] = item

                def convert(self):
                    """Convert the content read from file to the object itself."""
                    # py_obj_type should point to MyClass or any of its subclasses
                    new_instance = self.object_type.__new__(self.object_type)

                    if hasattr(new_instance, "__sethstate__"):
                        new_instance.__sethstate__(self._content)
                    elif hasattr(new_instance, "__setstate__"):
                        new_instance.__setstate__(self._content)
                    else:
                        new_instance.__dict__.update(self._content)

                    if hasattr(new_instance, "__attrs_post_init__"):
                        new_instance.__attrs_post_init__()

                    return new_instance

        else:
            _load_container = (
                load_container(cls) if callable(load_container) else load_container
            )

        LoaderManager.register_class(
            cls,
            hstr,
            dump_function=_dump_function,
            container_class=_load_container,
            **kwargs,
        )

        return cls

    return inner


# Make Path object dump well.
def _path_dump_function(py_obj, h_group, name, **kwargs):
    ds = h_group.create_dataset(name, data=str(py_obj))
    return ds, ()


def _load_path(h_node, base_type, py_obj_type):
    # py_obj_type should point to MyClass or any of its subclasses
    return Path(h_node[()].decode())


LoaderManager.register_class(
    Path,
    b"PosixPath",
    dump_function=_path_dump_function,
    load_function=_load_path,
)

if yaml is not None:
    # Register a YAML loader for hickle-dumped files.
    def _hickle_yaml_loader(path):
        return hickle.load(path)

    yaml.add_constructor("!hickle", _hickle_yaml_loader, Loader=yaml.FullLoader)
    yaml.add_constructor("!hickle", _hickle_yaml_loader, Loader=yaml.Loader)
