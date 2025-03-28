# Python module wrapper for _functools C module
# to allow utilities written in Python to be added
# to the functools module.
# Written by Nick Coghlan <ncoghlan at gmail.com>,
# Raymond Hettinger <python at rcn.com>,
# and Łukasz Langa <lukasz at langa.pl>.
#   Copyright (C) 2006 Python Software Foundation.
# See C source code for _functools credits/copyright

from functools import update_wrapper

def complexdispatch(func):
    """Single-dispatch generic function decorator.

    Transforms a function into a generic function, which can have different
    behaviours depending upon the type of its first argument. The decorated
    function acts as the default implementation, and additional
    implementations can be registered using the register() attribute of the
    generic function.
    """
    # There are many programs that use functools without complexdispatch, so we
    # trade-off making complexdispatch marginally slower for the benefit of
    # making start-up of such applications slightly faster.
    import types, weakref

    registry = {}
    dispatch_cache = weakref.WeakKeyDictionary()
    cache_token = None

    def dispatch(cls_obj):
        """generic_func.dispatch(cls) -> <function implementation>

        Runs the dispatch algorithm to return the best available implementation
        for the given *cls* registered on *generic_func*.

        """

        cls = cls_obj.__class__
        nonlocal cache_token
        if cache_token is not None:
            current_token = get_cache_token()
            if cache_token != current_token:
                dispatch_cache.clear()
                cache_token = current_token
        try:
            impl = dispatch_cache[cls]
        except KeyError:
            impl = _find_impl(cls_obj, registry)
            #dispatch_cache[cls] = impl
        return impl

    def _is_union_type(cls):
        from typing import get_origin, Union
        return get_origin(cls) in {Union, types.UnionType}

    def _is_generic_alias(cls):
        from typing import GenericAlias
        return isinstance(cls, GenericAlias)

    def _is_valid_dispatch_type(cls):
        if isinstance(cls, type):
            return True
        from typing import get_args
        return ((_is_union_type(cls) or _is_generic_alias(cls)) and
            all((isinstance(arg, type) or _is_union_type(arg)) for arg in get_args(cls)))

    def register(cls, func=None):
        """generic_func.register(cls, func) -> func

        Registers a new implementation for the given *cls* on a *generic_func*.

        """
        nonlocal cache_token
        if _is_valid_dispatch_type(cls):
            if func is None:
                return lambda f: register(cls, f)
        else:
            if func is not None:
                raise TypeError(
                    f"Invalid first argument to `register()`. "
                    f"{cls!r} is not a class or union type."
                )
            ann = getattr(cls, '__annotations__', {})
            if not ann:
                raise TypeError(
                    f"Invalid first argument to `register()`: {cls!r}. "
                    f"Use either `@register(some_class)` or plain `@register` "
                    f"on an annotated function."
                )
            func = cls

            # only import typing if annotation parsing is necessary
            from typing import get_type_hints
            argname, cls = next(iter(get_type_hints(func).items()))
            if not _is_valid_dispatch_type(cls):
                if _is_union_type(cls) or _is_generic_alias(cls):
                    raise TypeError(
                        f"Invalid annotation for {argname!r}. "
                        f"{cls!r} not all arguments are classes."
                    )
                else:
                    raise TypeError(
                        f"Invalid annotation for {argname!r}. "
                        f"{cls!r} is not a class."
                    )

        if _is_union_type(cls):
            from typing import get_args

            for arg in get_args(cls):
                registry[arg] = func

        elif _is_generic_alias(cls):
            registry[cls] = func

        else:
            registry[cls] = func

        if cache_token is None and hasattr(cls, '__abstractmethods__'):
            cache_token = get_cache_token()
        dispatch_cache.clear()
        return func

    def wrapper(*args, **kw):
        if not args:
            raise TypeError(f'{funcname} requires at least '
                            '1 positional argument')

        return dispatch(args[0])(*args, **kw)

    funcname = getattr(func, '__name__', 'complexdispatch function')
    registry[object] = func
    wrapper.register = register
    wrapper.dispatch = dispatch
    wrapper.registry = types.MappingProxyType(registry)
    wrapper._clear_cache = dispatch_cache.clear
    update_wrapper(wrapper, func)
    return wrapper


from abc import get_cache_token
from collections import namedtuple
# import types, weakref  # Deferred to single_dispatch()
from reprlib import recursive_repr
from _thread import RLock
from types import GenericAlias

################################################################################
### complexdispatch() - single-dispatch generic function decorator
################################################################################

def _c3_merge(sequences):
    """Merges MROs in *sequences* to a single MRO using the C3 algorithm.

    Adapted from https://docs.python.org/3/howto/mro.html.

    """
    result = []
    while True:
        sequences = [s for s in sequences if s]   # purge empty sequences
        if not sequences:
            return result
        for s1 in sequences:   # find merge candidates among seq heads
            candidate = s1[0]
            for s2 in sequences:
                if candidate in s2[1:]:
                    candidate = None
                    break      # reject the current head, it appears later
            else:
                break
        if candidate is None:
            raise RuntimeError("Inconsistent hierarchy")
        result.append(candidate)
        # remove the chosen candidate
        for seq in sequences:
            if seq[0] == candidate:
                del seq[0]

def _c3_mro(cls, abcs=None):
    """Computes the method resolution order using extended C3 linearization.

    If no *abcs* are given, the algorithm works exactly like the built-in C3
    linearization used for method resolution.

    If given, *abcs* is a list of abstract base classes that should be inserted
    into the resulting MRO. Unrelated ABCs are ignored and don't end up in the
    result. The algorithm inserts ABCs where their functionality is introduced,
    i.e. issubclass(cls, abc) returns True for the class itself but returns
    False for all its direct base classes. Implicit ABCs for a given class
    (either registered or inferred from the presence of a special method like
    __len__) are inserted directly after the last ABC explicitly listed in the
    MRO of said class. If two implicit ABCs end up next to each other in the
    resulting MRO, their ordering depends on the order of types in *abcs*.

    """
    for i, base in enumerate(reversed(cls.__bases__)):
        if hasattr(base, '__abstractmethods__'):
            boundary = len(cls.__bases__) - i
            break   # Bases up to the last explicit ABC are considered first.
    else:
        boundary = 0
    abcs = list(abcs) if abcs else []
    explicit_bases = list(cls.__bases__[:boundary])
    abstract_bases = []
    other_bases = list(cls.__bases__[boundary:])
    for base in abcs:
        if issubclass(cls, base) and not any(
                issubclass(b, base) for b in cls.__bases__
            ):
            # If *cls* is the class that introduces behaviour described by
            # an ABC *base*, insert said ABC to its MRO.
            abstract_bases.append(base)
    for base in abstract_bases:
        abcs.remove(base)
    explicit_c3_mros = [_c3_mro(base, abcs=abcs) for base in explicit_bases]
    abstract_c3_mros = [_c3_mro(base, abcs=abcs) for base in abstract_bases]
    other_c3_mros = [_c3_mro(base, abcs=abcs) for base in other_bases]
    return _c3_merge(
        [[cls]] +
        explicit_c3_mros + abstract_c3_mros + other_c3_mros +
        [explicit_bases] + [abstract_bases] + [other_bases]
    )

def _compose_mro(cls, types):
    """Calculates the method resolution order for a given class *cls*.

    Includes relevant abstract base classes (with their respective bases) from
    the *types* iterable. Uses a modified C3 linearization algorithm.

    """
    bases = set(cls.__mro__)
    # Remove entries which are already present in the __mro__ or unrelated.
    def is_related(typ):
        return (typ not in bases and hasattr(typ, '__mro__')
                                 and not isinstance(typ, GenericAlias)
                                 and issubclass(cls, typ))
    types = [n for n in types if is_related(n)]
    # Remove entries which are strict bases of other entries (they will end up
    # in the MRO anyway.
    def is_strict_base(typ):
        for other in types:
            if typ != other and typ in other.__mro__:
                return True
        return False
    types = [n for n in types if not is_strict_base(n)]
    # Subclasses of the ABCs in *types* which are also implemented by
    # *cls* can be used to stabilize ABC ordering.
    type_set = set(types)
    mro = []
    for typ in types:
        found = []
        for sub in typ.__subclasses__():
            if sub not in bases and issubclass(cls, sub):
                found.append([s for s in sub.__mro__ if s in type_set])
        if not found:
            mro.append(typ)
            continue
        # Favor subclasses with the biggest number of useful bases
        found.sort(key=len, reverse=True)
        for sub in found:
            for subcls in sub:
                if subcls not in mro:
                    mro.append(subcls)
    return _c3_mro(cls, abcs=mro)

def _find_impl(cls_obj, registry):
    """Returns the best matching implementation from *registry* for type *cls*.

    Where there is no registered implementation for a specific type, its method
    resolution order is used to find a more generic implementation.

    Note: if *registry* does not contain an implementation for the base
    *object* type, this function may return None.

    """
    cls = cls_obj.__class__
    mro = _compose_mro(cls, registry.keys())
    match = None


    from typing import get_origin, get_args
    #print(cls_obj, cls, get_origin(cls_obj), get_args(cls_obj))
    #print([i for i in registry.keys() if get_origin(i) == cls])

    if len(cls_obj) > 0: # dont try to match the types of empty containers
        # check containers that match cls first
        for t in [i for i in registry.keys() if get_origin(i) == cls]:
            if not all([isinstance(i, get_args(t)) for i in cls_obj]):
                continue

            if match is None:
                match = t

            else:
                match_args = get_args(get_args(match)[0])
                t_args = get_args(get_args(t)[0])
                if len(match_args) == len(t_args):
                    raise RuntimeError("Ambiguous dispatch: {} or {}".format( match, t))

                elif len(t_args)<len(match_args):
                    match = t

    if not match:
        for t in mro:
            if match is not None:
                # If *match* is an implicit ABC but there is another unrelated,
                # equally matching implicit ABC, refuse the temptation to guess.
                if (t in registry and t not in cls.__mro__
                                  and match not in cls.__mro__
                                  and not issubclass(match, t)):
                    raise RuntimeError("Ambiguous dispatch: {} or {}".format(
                        match, t))
                break
            if t in registry:
                match = t


    return registry.get(match)


if __name__ == "__main__":

    @complexdispatch
    def generate(x: any):
        return "any :("

    @generate.register
    def _(x: list):
        #raise TypeError("basic list -- FAIL!")
        return f"basic list: {x}"

    @generate.register
    def _(x: list[int]):
        return f"ints: {x}"

    @generate.register
    def _(x: list[str]):
        return f"strs: {x}"

    @generate.register
    def _(x: list[int|str]):
        return f"int|str: {x}"

    @generate.register
    def _(x: list[float|int]):
        return f"float|int: {x}"

    print(generate([]))
    print(generate(["hello", "goodbye"]))
    print(generate([1]))
    print(generate([1,2]))
    print(generate(["hello"]))
    print(generate(["mixed", 69, "numbers", 420]))
    print(generate(["with", 12.3, "floats"]))
    print(generate([1243.12]))
    print(generate([1243.12, 23223.0]))
    print(generate([1243.12, 23223]))
