"""Separate, syscall-filtered executor for generated robot methods.

No environment, credentials, files, or network are exposed. Physical actions
require synchronous host RPC. A source check is defense in depth, not isolation.
"""
from __future__ import annotations

import ast
import ctypes
import ctypes.util
import json
import math
import resource
import sys


def validate_source(source):
    if not isinstance(source, str) or not source.isascii() or len(source) > 120000:
        raise ValueError("Expected at most 120000 ASCII source characters")
    tree = ast.parse(source)
    forbidden = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.With, ast.AsyncWith,
                 ast.AsyncFunctionDef, ast.While, ast.Global, ast.Nonlocal)
    banned = {"open", "eval", "exec", "compile", "getattr", "setattr", "delattr",
              "globals", "locals", "vars", "dir", "input", "breakpoint", "help"}
    for node in ast.walk(tree):
        if isinstance(node, forbidden):
            raise ValueError("Unsupported source construct: " + type(node).__name__)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Private attributes are unavailable")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id in banned):
            raise ValueError("Unsupported name: " + node.id)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body):
        raise ValueError("Define main(api)")
    return tree


def restrict_syscalls():
    """Default-deny Linux syscalls after Python/NumPy have been loaded."""
    name = ctypes.util.find_library("seccomp")
    if not name:
        raise RuntimeError("libseccomp is required; refuse to execute")
    lib = ctypes.CDLL(name, use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x00050000 | 1)  # EPERM unless explicitly allowed.
    if not context:
        raise RuntimeError("Cannot create syscall filter")
    allowed = "read write readv writev close fstat lseek poll ppoll select pselect6 futex clock_gettime clock_getres gettimeofday time nanosleep clock_nanosleep brk mmap munmap mremap mprotect madvise rt_sigaction rt_sigprocmask rt_sigreturn sigaltstack getpid gettid sched_yield getrandom exit exit_group restart_syscall".split()
    try:
        for call in allowed:
            number = lib.seccomp_syscall_resolve_name(call.encode())
            if number >= 0 and lib.seccomp_rule_add(context, 0x7FFF0000, number, 0):
                raise RuntimeError("Cannot allow syscall: " + call)
        if lib.seccomp_load(context):
            raise RuntimeError("Cannot load syscall filter")
    finally:
        lib.seccomp_release(context)


def worker():
    import numpy as np
    request = json.loads(sys.stdin.readline())
    tree = validate_source(request["source"])
    code = compile(tree, "generated-method", "exec")
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    incoming, outgoing = sys.stdin, sys.stdout

    def send(value):
        outgoing.write(json.dumps(value, allow_nan=False) + "\n")
        outgoing.flush()

    class RPC:
        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            def call(*args, **kwargs):
                send(dict(kind="rpc", method=name, args=args, kwargs=kwargs))
                response = json.loads(incoming.readline())
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response["result"]
            return call

    safe = {}
    import builtins
    for name in ("abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
                 "len", "list", "max", "min", "range", "reversed", "round", "set",
                 "sorted", "str", "sum", "tuple", "zip", "isinstance", "type", "Exception",
                 "RuntimeError", "ValueError"):
        safe[name] = getattr(builtins, name)
    def program_print(*items, **kwargs):
        return RPC().note(" ".join(str(item) for item in items)[:4000])
    safe["print"] = program_print
    namespace = dict(__builtins__=safe, np=np, math=math)
    restrict_syscalls()
    send(dict(kind="sandbox", isolation="separate_process_default_deny_seccomp"))
    if not json.loads(incoming.readline()).get("ready"):
        raise RuntimeError("Host did not acknowledge sandbox")
    try:
        exec(code, namespace)
        result = namespace["main"](RPC())
        send(dict(kind="result", result=result))
    except BaseException as error:
        send(dict(kind="error", error=type(error).__name__ + ": " + str(error)[:1200]))


if __name__ == "__main__":
    worker()
