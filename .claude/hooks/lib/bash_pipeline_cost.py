#!/usr/bin/env python3
"""Estimate a narrowly recognized small-output pipeline without executing it.

Unknown shell syntax produces no estimate; the caller keeps its conservative
fallback. Line limits are estimates (128 bytes/line), not byte guarantees. Use
head -c for an explicit byte cap. Large numeric limits retain their large cost.
Help/version output filtered on stdin returns 'bounded' for the policy's fixed
bounded-command charge. Like that existing charge, this is a heuristic.
"""

import re
import shlex
import sys


LINE_ESTIMATE_BYTES = 128
PRODUCERS = {"cat", "find", "grep", "rg"}


def shell_tokens(command):
    """Keep operator provenance: a quoted/escaped '|' is an argument.

    Split only unquoted operators, then let shlex decode the word spans.
    Expansions, grouping and newlines are rejected by estimate beforehand.
    """
    tokens = []
    start = i = 0
    quote = None
    while i < len(command):
        char = command[i]
        if char == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "#" and (i == 0 or command[i - 1].isspace() or command[i - 1] in ";&|<>"):
            command = command[:i]
            break
        elif char in ";&|<>":
            tokens.extend(("word", word) for word in shlex.split(command[start:i]))
            end = i + 1
            while end < len(command) and command[end] in ";&|<>":
                end += 1
            tokens.append(("operator", command[i:end]))
            start = i = end
            continue
        i += 1
    tokens.extend(("word", word) for word in shlex.split(command[start:]))
    return tokens


def command_name(token):
    for prefix in ("/usr/bin/", "/bin/"):
        if token.startswith(prefix):
            return token[len(prefix):]
    return token


def head_bytes(args):
    if not args:
        return 10 * LINE_ESTIMATE_BYTES
    value = None
    unit = LINE_ESTIMATE_BYTES
    if len(args) == 2 and args[0] in ("-n", "--lines", "-c", "--bytes"):
        unit = 1 if args[0] in ("-c", "--bytes") else LINE_ESTIMATE_BYTES
        value = args[1]
    elif len(args) == 1:
        match = re.fullmatch(r"(-n|--lines=|-c|--bytes=|-)([0-9]+)", args[0])
        if match:
            unit = 1 if match[1] in ("-c", "--bytes=") else LINE_ESTIMATE_BYTES
            value = match[2]
    # Negative counts mean 'all but the last N', not a cap. Suffixes,
    # duplicate flags and file operands are deliberately unsupported.
    if value is None or re.fullmatch(r"[0-9]{1,12}", value) is None:
        return None
    return int(value) * unit


def is_help_command(stage):
    # A bare CLI with optional subcommand names and a final help/version
    # flag. Do not mistake 'sh -c CODE --help' for help output.
    return (len(stage) >= 2 and stage[-1] in ("--help", "--version")
            and re.fullmatch(r"[A-Za-z0-9_./-]+", stage[0]) is not None
            and command_name(stage[0]) not in PRODUCERS
            and all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", arg)
                    for arg in stage[1:-1]))


def is_stdin_filter(stage):
    if command_name(stage[0]) not in {"grep", "rg"}:
        return False
    args = stage[1:]
    while args and re.fullmatch(r"-[invEFwxcq]+", args[0]):
        args = args[1:]
    # Exactly one pattern, no file operand or pattern file. A file operand
    # would replace stdin with a new, independently unbounded source.
    return len(args) == 1 and not args[0].startswith("-")


def estimate(command):
    # shlex is a tokenizer, not a shell parser. Refuse expansion, multiline
    # commands and grouping before tokenization can erase their provenance.
    if any(char in command for char in ("$", "`", "\n", "\r", "(", ")")):
        return None
    try:
        tokens = shell_tokens(command)
    except ValueError:
        return None

    # cd itself emits no stdout for a literal directory. Only this one
    # leading chain is recognized; later chains may emit outside the pipe.
    if (len(tokens) >= 4 and tokens[0] == ("word", "cd")
            and tokens[1][0] == "word" and not tokens[1][1].startswith("-")):
        if tokens[2] in (("operator", "&&"), ("operator", ";")):
            tokens = tokens[3:]

    stages = [[]]
    i = 0
    while i < len(tokens):
        kind, token = tokens[i]
        # Silence stderr or merge it into the pipeline. Other redirections
        # can detach the limiter from its producer and are not recognized.
        if tokens[i:i + 3] in (
            [("word", "2"), ("operator", ">"), ("word", "/dev/null")],
            [("word", "2"), ("operator", ">&"), ("word", "1")],
        ):
            i += 3
            continue
        if kind == "operator" and token == "|":
            if not stages[-1]:
                return None
            stages.append([])
        elif kind == "operator":
            return None
        else:
            stages[-1].append(token)
        i += 1

    if len(stages) < 2 or not all(stages):
        return None
    if is_help_command(stages[0]) and all(is_stdin_filter(stage) for stage in stages[1:]):
        return "bounded"
    if not (command_name(stages[0][0]) in PRODUCERS or is_help_command(stages[0])):
        return None
    if any(command_name(stage[0]) not in PRODUCERS for stage in stages[1:-1]):
        return None
    if command_name(stages[-1][0]) != "head":
        return None
    return head_bytes(stages[-1][1:])


if __name__ == "__main__":
    cost = estimate(sys.stdin.read())
    if cost is not None:
        print(cost)
