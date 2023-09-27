# -----------------------------------------------------------------------------
# ply: cpp.py
#
# Copyright (C) 2001-2019
# David M. Beazley (Dabeaz LLC)
# All rights reserved.
#
# Latest version: https://github.com/dabeaz/ply
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of David Beazley or Dabeaz LLC may be used to
#   endorse or promote products derived from this software without
#   specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# -----------------------------------------------------------------------------

# This module implements an ANSI-C style lexical preprocessor for PLY.
# -----------------------------------------------------------------------------
from __future__ import (
    generators,
)

from copy import (
    copy,
)
from os.path import (
    basename,
    dirname,
    join,
)
from re import (
    compile as compile_re,
)
from sys import (
    version_info,
)
from time import (
    localtime,
    strftime,
)
from warnings import (
    catch_warnings,
    simplefilter,
)


# Some Python 3 compatibility shims
if version_info.major < 3:
    STRING_TYPES = (str, unicode)

    def read_include_file(filepath):
        with open(filepath) as file:
            return file.read()
else:
    STRING_TYPES = str
    xrange = range

    def read_include_file(filepath):
        with open(filepath, 'r',
            encoding = 'utf-8',
            errors = 'surrogateescape'
        ) as file:
            return file.read()

read_include_file.__doc__ = """\
Reads a source file for inclusion using #include
Could be overridden to e.g. customize encoding, limit access to
certain paths on the filesystem, or provide the contents of system
include files.
"""

# -----------------------------------------------------------------------------
# Default preprocessor lexer definitions.   These tokens are enough to get
# a basic preprocessor working.   Other modules may import these if they want
# -----------------------------------------------------------------------------

tokens = (
   'CPP_ID','CPP_INTEGER', 'CPP_FLOAT', 'CPP_STRING', 'CPP_CHAR', 'CPP_WS', 'CPP_COMMENT1', 'CPP_COMMENT2', 'CPP_POUND','CPP_DPOUND'
)

literals = "+-*/%|&~^<>=!?()[]{}.,;:\\\'\""

# Whitespace
def t_CPP_WS(t):
    r'\s+'
    t.lexer.lineno += t.value.count("\n")
    return t

t_CPP_POUND = r'\#'
t_CPP_DPOUND = r'\#\#'

# Identifier
t_CPP_ID = r'[A-Za-z_][\w_]*'

# Integer literal
def CPP_INTEGER(t):
    r'(((((0x)|(0X))[0-9a-fA-F]+)|(\d+))([uU][lL]|[lL][uU]|[uU]|[lL])?)'
    return t

t_CPP_INTEGER = CPP_INTEGER

# Floating literal
t_CPP_FLOAT = r'((\d+)(\.\d+)(e(\+|-)?(\d+))? | (\d+)e(\+|-)?(\d+))([lL]|[fF])?'

# String literal
def t_CPP_STRING(t):
    r'\"([^\\\n]|(\\(.|\n)))*?\"'
    t.lexer.lineno += t.value.count("\n")
    return t

# Character constant 'c' or L'c'
def t_CPP_CHAR(t):
    r'(L)?\'([^\\\n]|(\\(.|\n)))*?\''
    t.lexer.lineno += t.value.count("\n")
    return t

# Comment
def t_CPP_COMMENT1(t):
    r'(/\*(.|\n)*?\*/)'
    ncr = t.value.count("\n")
    t.lexer.lineno += ncr
    # replace with one space or a number of '\n'
    t.type = 'CPP_WS'; t.value = '\n' * ncr if ncr else ' '
    return t

# Line comment
def t_CPP_COMMENT2(t):
    r'(//.*?(\n|$))'
    # replace with '/n'
    t.type = 'CPP_WS'; t.value = '\n'
    return t

def t_error(t):
    t.type = t.value[0]
    t.value = t.value[0]
    t.lexer.skip(1)
    return t


def trigraph(s):
    """ Given an input string, this function replaces all trigraph sequences.
The following mapping is used:

  ??=    #
  ??/    \
  ??'    ^
  ??(    [
  ??)    ]
  ??!    |
  ??<    {
  ??>    }
  ??-    ~
    """
    return _trigraph_pat.sub(_trigraph_pat_sub, s)

_trigraph_pat = compile_re(r'''\?\?[=/\'\(\)\!<>\-]''')
_trigraph_rep = {
    '=':'#',
    '/':'\\',
    "'":'^',
    '(':'[',
    ')':']',
    '!':'|',
    '<':'{',
    '>':'}',
    '-':'~'
}

_trigraph_pat_sub = lambda g: _trigraph_rep[g.group()[-1]]


class Macro(object):
    """ Macro object
This object holds information about preprocessor macros.

.name      - Macro name (string)
.value     - Macro value (a list of tokens)
.arglist   - List of argument names
.vararg    - Name of the variadic parameter, None if macro is not variadic

When a macro is created, the macro replacement token sequence is
pre-scanned and used to create patch lists that are later used
during macro expansion.
    """

    vararg = None

    def __init__(self, name, value, arglist = None, variadic = None):
        self.name = name
        self.value = value
        self.arglist = arglist
        if variadic:
            self.vararg = arglist[-1]
        self.source = None

    @property
    def variadic(self):
        return self.vararg is not None


at_index_2 = lambda x: x[2]
copy_tokens = lambda tokens : list(map(copy, tokens))

class Preprocessor(object):
    """ Preprocessor object.

Object representing a preprocessor.
Contains macro definitions, include directories, and other information.
    """

    def __init__(self, lexer = None):
        if lexer is None:
            lexer = lex.lexer
        self.lexer = lexer
        self.macros = {}
        self.path = []
        self.temp_path = []

        # Probe the lexer for selected tokens
        self.lexprobe()

        tm = localtime()
        self.define('__DATE__ "%s"' % strftime("%b %d %Y",tm))
        self.define('__TIME__ "%s"' % strftime("%H:%M:%S",tm))
        self.parser = None

    @property
    def full_source_path(self):
        if self.temp_path:
            return join(self.temp_path[0], basename(self.source))
        else:
            return self.source

    def tokenize(self, text):
        """ Utility function.
Given a string of text, tokenize into a list of tokens.
        """
        tokens = []

        self.lexer.input(text)

        # cache
        token = self.lexer.token
        append = tokens.append

        tok = token()
        while tok:
            append(tok)
            tok = token()

        return tokens

    def error(self, file, line, msg):
        """ Report a preprocessor error/warning of some kind.
        """
        print("%s:%d %s" % (file, line, msg))

    def lexprobe(self):
        """ This method probes the preprocessor lexer object to discover
the token types of symbols that are important to the preprocessor.
If this works right, the preprocessor will simply "work" with any suitable
lexer regardless of how tokens have been named.
        """

        # cache
        set_lexer_input = self.lexer.input
        get_next_token = self.lexer.token

        # Determine the token type for identifiers
        set_lexer_input("identifier")
        tok = get_next_token()
        if not tok or tok.value != "identifier":
            print("Couldn't determine identifier type")
        else:
            self.t_ID = tok.type

        # Determine the token type for integers
        set_lexer_input("12345")
        tok = get_next_token()
        if not tok or int(tok.value) != 12345:
            print("Couldn't determine integer type")
        else:
            self.t_INTEGER = tok.type
            self.t_INTEGER_TYPE = type(tok.value)

        # Determine the token type for strings enclosed in double quotes
        set_lexer_input('"filename"')
        tok = get_next_token()
        if not tok or tok.value != '"filename"':
            print("Couldn't determine string type")
        else:
            self.t_STRING = tok.type

        # Determine the token type for whitespace -- if any
        set_lexer_input("  ")
        tok = get_next_token()
        if not tok or tok.value != "  ":
            self.t_SPACE = None
        else:
            self.t_SPACE = tok.type

        # Determine the token type for newlines
        set_lexer_input("\n")
        tok = get_next_token()
        if not tok or tok.value != "\n":
            self.t_NEWLINE = None
            print("Couldn't determine token for newlines")
        else:
            self.t_NEWLINE = tok.type

        self.t_WS = (self.t_SPACE, self.t_NEWLINE)

        # Check for other characters used by the preprocessor
        chars = ('<', '>', '#', '##', '\\', '(', ')', ',', '.')
        for c in chars:
            set_lexer_input(c)
            tok = get_next_token()
            if not tok or tok.value != c:
                print("Unable to lex '%s' required for preprocessor" % c)

    def add_path(self,path):
        """ Adds a search path to the preprocessor.
        """
        self.path.append(path)

    def concat_lines(self, string):
        cur = ""
        cnt = 0

        for l in string.splitlines():
            l = l.rstrip()
            if l.endswith('\\'):
                cur += l[:-1]
                cnt += 1
            elif cnt:
                yield cur + l
                for __ in range(cnt):
                    yield ""
                cur = ""
                cnt = 0
            else:
                yield l

        if cnt:
            yield cur
            for __ in range(cnt):
                yield ""

    def group_lines(self, text):
        """ Given an input text, this function splits it into lines.
Trailing whitespace is removed.
Any line ending with \ is concatenated with the next line.
This function forms the lowest level of the preprocessor --- grouping input
text into a line-by-line format.
        """
        text = "\n".join(self.concat_lines(text))

        lex = self.lexer.clone()
        lex.input(text)
        lex.lineno = 1

        # cache
        WS = self.t_WS
        token = lex.token

        current_line = []
        tok = token()
        while tok:
            current_line.append(tok)
            if tok.type in WS and '\n' in tok.value:
                yield current_line
                current_line = []
            tok = token()

        if current_line:
            yield current_line

    def tokenstrip(self, tokens):
        """ Remove leading/trailing whitespace tokens from a token list.
        """
        t_WS = self.t_WS

        for i, t in enumerate(tokens):
            if t.type not in t_WS:
                del tokens[:i]
                for i, t in enumerate(reversed(tokens)):
                    if t.type not in t_WS:
                        if i:
                            del tokens[-i:]
                        break
                break
        else:
            del tokens[:]

        return tokens

    def collect_args(self, tokenlist):
        """ Collects comma separated arguments from a list of tokens.
The arguments must be enclosed in parenthesis.
Returns a tuple (tokencount, args, positions) where
- tokencount is the number of tokens consumed,
- args is a list of arguments, and
- positions is a list of integers containing the starting index of each
  argument.
Each argument is represented by a list of tokens.

When collecting arguments, leading and trailing whitespace is removed from
each argument.

This function properly handles nested parenthesis and commas --- these do not
define new arguments.
        """

        # cache
        WS = self.t_WS

        args = []
        positions = []
        current_arg = []
        nesting = 1
        tokenlen = len(tokenlist)

        # Search for the opening '('.
        i = 0
        while (i < tokenlen) and (tokenlist[i].type in WS):
            i += 1

        if (i < tokenlen) and (tokenlist[i].value == '('):
            positions.append(i + 1)
        else:
            self.error(
                self.source,
                tokenlist[0].lineno,
                "Missing '(' in macro arguments"
            )
            return (0, [], [])

        i += 1

        while i < tokenlen:
            t = tokenlist[i]
            if t.value == '(':
                current_arg.append(t)
                nesting += 1
            elif t.value == ')':
                nesting -= 1
                if nesting == 0:
                    if current_arg:
                        args.append(self.tokenstrip(current_arg))
                        positions.append(i)
                    return (i + 1, args, positions)
                current_arg.append(t)
            elif t.value == ',' and nesting == 1:
                args.append(self.tokenstrip(current_arg))
                positions.append(i + 1)
                current_arg = []
            else:
                current_arg.append(t)
            i += 1

        # Missing end argument
        self.error(
            self.source,
            tokenlist[-1].lineno,
            "Missing ')' in macro arguments"
        )
        return (0, [],[])

    def macro_prescan(self, macro):
        """ Examine the macro value (token sequence) and identify patch points.
This is used to speed up macro expansion later on --- we'll know right away
where to apply patches to the value to form the expansion.
        """
        # Standard macro arguments
        macro.patch = patch = []
        # String conversion expansion
        macro.str_patch = str_patch = []
        # Variadic macro comma patch
        macro.var_comma_patch = var_comma_patch = []

        # cache
        vararg = macro.vararg
        arglist = macro.arglist
        value = macro.value
        t_ID = self.t_ID

        i = 0
        while i < len(value):
            t = value[i]
            if t.type == t_ID and t.value in arglist:
                argnum = arglist.index(t.value)
                # Conversion of argument to a string
                if i > 0 and value[i - 1].value == '#':
                    value[i] = copy(t)
                    value[i].type = self.t_STRING
                    del value[i - 1]
                    str_patch.append((argnum, i - 1))
                    continue
                # Concatenation
                elif (i > 0 and value[i - 1].value == '##'):
                    patch.append(('c', argnum, i - 1))
                    del value[i - 1]
                    i -= 1
                    continue
                elif ((i + 1) < len(value) and value[i + 1].value == '##'):
                    patch.append(('c', argnum, i))
                    del value[i + 1]
                    continue
                # Standard expansion
                else:
                    patch.append(('e', argnum, i))
            elif vararg is not None and t.value == '##':
                if (
                       (i > 0)
                   and (value[i - 1].value == ',')
                   and ((i + 1) < len(value))
                   and (value[i + 1].type == t_ID)
                   and (value[i + 1].value == vararg)
                ):
                    var_comma_patch.append(i - 1)
            i += 1

        patch.sort(key = at_index_2, reverse = True)

    def macro_expand_args(self, macro, args, *ctx):
        """ Given a Macro and list of arguments (each a token list), this
method returns an expanded version of a macro.
The return value is a token sequence representing the replacement macro tokens.
        """

        rep = copy_tokens(macro.value)

        # Make string expansion patches.
        # These do not alter the length of the replacement sequence
        str_expansion = {}
        for argnum, i in macro.str_patch:
            if argnum not in str_expansion:
                str_expansion[argnum] = (
                    '"%s"' % "".join(x.value for x in args[argnum])
                ).replace("\\", "\\\\")
            rep[i].value = str_expansion[argnum]

        # Make the variadic macro comma patch.
        # If the variadic macro argument is empty, we get rid
        comma_patch = False
        if macro.vararg is not None and not args[-1]:
            for i in macro.var_comma_patch:
                rep[i] = None
                comma_patch = True

        # Make all other patches.
        # The order of these matters.
        # It is assumed that the patch list has been sorted in reverse order
        # of patch location since replacements will cause the size of the
        # replacement sequence to expand from the patch point.

        expanded_args = {}
        for ptype, argnum, i in macro.patch:
            # Concatenation.
            # Argument is left unexpanded
            if ptype == 'c':
                rep[i:i + 1] = args[argnum]
            # Normal expansion.
            # Argument is macro expanded first
            elif ptype == 'e':
                if argnum not in expanded_args:
                    expanded_args[argnum] \
                        = self.expand_macros(args[argnum], *ctx)

                rep[i:i + 1] = expanded_args[argnum]

        # Get rid of removed comma if necessary
        if comma_patch:
            rep = [_i for _i in rep if _i is not None]

        return rep

    def expand_macros(self, tokens, expanded = None):
        """ Given a list of tokens, this function performs macro expansion.
The expanded argument is a dictionary that contains macros already expanded.
This is used to prevent infinite recursion.
        """

        # cache
        macros = self.macros
        WS = self.t_WS

        if expanded is None:
            expanded = set()

        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.type != self.t_ID:
                i += 1
                continue

            # cache
            t_value = t.value

            if t_value in macros and t_value not in expanded:
                # Yes, we found a macro match
                expanded.add(t_value)

                m = macros[t_value]
                arglist = m.arglist

                if arglist:
                    # A macro with arguments
                    j = i + 1
                    while j < len(tokens) and tokens[j].type in WS:
                        j += 1

                    if j < len(tokens) and tokens[j].value == '(':

                        tokcount, args, positions \
                            = self.collect_args(tokens[j:])

                        variadic = m.variadic

                        if not variadic and len(args) != len(arglist):
                            self.error(
                                self.source,
                                t.lineno,
                                "Macro %s requires %d arguments" % (
                                    t_value,
                                    len(arglist),
                                )
                            )
                            i = j + tokcount

                        elif variadic and len(args) < len(arglist) - 1:
                            if len(arglist) > 2:
                                self.error(
                                    self.source,
                                    t.lineno,
                                    "Macro %s must have"
                                    " at least %d arguments" % (
                                        t_value,
                                        len(arglist) - 1),
                                    )
                            else:
                                self.error(
                                    self.source,
                                    t.lineno,
                                    "Macro %s must have"
                                    " at least 1 argument" % (t_value,)
                                )
                            i = j + tokcount
                        else:
                            if variadic:
                                if len(args) == len(arglist) - 1:
                                    args.append([])
                                else:
                                    args[len(arglist) - 1] \
                                        = tokens[
                                            j + positions[len(arglist) - 1]
                                            :
                                            j + tokcount - 1  # except ')'
                                        ]
                                    del args[len(arglist):]

                            # Get macro replacement text
                            rep = self.macro_expand_args(m, args, expanded)
                            rep = self.expand_macros(rep, expanded)

                            for r in rep:
                                r.lineno = t.lineno

                            tokens[i : j + tokcount] = rep
                            i += len(rep)
                    else:
                        # This is not a macro. It is just a word which
                        # equals to name of the macro. Hence, go to the
                        # next token.
                        i += 1
                else:
                    # A simple macro
                    ex = self.expand_macros(copy_tokens(m.value), expanded)

                    for e in ex:
                        e.lineno = t.lineno

                    tokens[i:i + 1] = ex
                    i += len(ex)

                expanded.remove(t_value)
                continue

            elif t_value == '__LINE__':
                t.type = self.t_INTEGER
                t.value = self.t_INTEGER_TYPE(t.lineno)

            i += 1

        return tokens

    def evalexpr(self, tokens):
        """ Evaluate an expression token sequence for the purposes of
evaluating integral expressions.
        """

        # cache
        ID = self.t_ID
        WS = self.t_WS
        macros = self.macros

        # Search for defined macros
        i = 0
        while i < len(tokens):
            ti = tokens[i]
            if ti.type == ID and ti.value == 'defined':
                j = i + 1
                needparen = False
                result = "0L"
                while j < len(tokens):
                    tj = tokens[j]
                    if tj.type in WS:
                        j += 1
                        continue
                    elif tj.type == ID:
                        if tj.value in macros:
                            result = "1L"
                        else:
                            result = "0L"
                        if not needparen:
                            break
                    elif tj.value == '(':
                        needparen = True
                    elif tj.value == ')':
                        break
                    else:
                        self.error(
                            self.source,
                            ti.lineno,
                            "Malformed defined()"
                        )
                    j += 1
                ti.type = self.t_INTEGER
                ti.value = self.t_INTEGER_TYPE(result)
                del tokens[i + 1:j + 1]
            i += 1

        tokens = self.expand_macros(tokens)
        return self.evalexpr_expanded(tokens)

    def evalexpr_expanded(self, tokens):
        """ Helper for evalexpr that evaluates the expression that had
its macros and defined(...) expressions expanded by evalexpr.
        """

        # cache
        ID = self.t_ID
        INTEGER = self.t_INTEGER

        for i, t in enumerate(tokens):
            if t.type == ID:
                tokens[i] = t = copy(t)
                t.type = INTEGER
                t.value = "0"
            elif t.type == INTEGER:
                tokens[i] = t = copy(t)
                # Strip off any trailing suffixes
                value = str(t.value)
                while value[-1] not in "0123456789abcdefABCDEF":
                    value = value[:-1]
                t.value = value

        return self.evalexpr_string(tokens)

    def evalexpr_string(self, tokens):
        """ Helper for evalexpr that evaluates a string expression.
This implementation does basic C->python conversion and then uses eval().
        """
        expr = "".join(x.value for x in tokens)

        expr = expr.replace("&&", " and ")
        expr = expr.replace("||", " or ")
        expr = expr.replace("!", " not ")
        expr = expr.replace(" not =", " !=")
        try:
            with catch_warnings():
                simplefilter("ignore")
                result = eval(expr)
        except Exception:
            self.error(
                self.source,
                tokens[0].lineno,
                "Couldn't evaluate expression"
            )
            result = 0
        return result

    def parsegen(self, text, source = None):
        """ Parse an input string.
        """

        # Replace trigraph sequences
        t = trigraph(text)
        lines = self.group_lines(t)

        if not source:
            source = ""

        self.define('__FILE__ "%s"' % source)

        self.source = source
        chunk = []
        enable = True
        iftrigger = False
        ifstack = []

        for l in lines:
            for i, tok in enumerate(l):
                if tok.type not in self.t_WS:
                    break

            if tok.value == '#':
                # Preprocessor directive

                # insert necessary whitespace instead of eaten tokens
                for tok in l:
                    if tok.type in self.t_WS and '\n' in tok.value:
                        chunk.append(tok)

                dirtokens = self.tokenstrip(l[i + 1:])
                if dirtokens:
                    name = dirtokens[0].value
                    args = self.tokenstrip(dirtokens[1:])
                else:
                    name = ""
                    args = []

                if name == 'define':
                    if enable:
                        for tok in self.expand_macros(chunk):
                            yield tok
                        chunk *= 0
                        self.define(args)

                elif name == 'include':
                    if enable:
                        for tok in self.expand_macros(chunk):
                            yield tok
                        chunk *= 0
                        oldfile = self.macros['__FILE__']
                        for tok in self.include(args):
                            yield tok
                        self.macros['__FILE__'] = oldfile
                        self.source = source

                elif name == 'undef':
                    if enable:
                        for tok in self.expand_macros(chunk):
                            yield tok
                        chunk *= 0
                        self.undef(args)

                elif name == 'ifdef':
                    ifstack.append((enable, iftrigger))
                    if enable:
                        if args[0].value in self.macros:
                            iftrigger = True
                        else:
                            enable = False
                            iftrigger = False

                elif name == 'ifndef':
                    ifstack.append((enable, iftrigger))
                    if enable:
                        if args[0].value not in self.macros:
                            iftrigger = True
                        else:
                            enable = False
                            iftrigger = False

                elif name == 'if':
                    ifstack.append((enable, iftrigger))
                    if enable:
                        if self.evalexpr(args):
                            iftrigger = True
                        else:
                            enable = False
                            iftrigger = False

                elif name == 'elif':
                    if ifstack:
                        # We only pay attention if outer "if" allows this.
                        # If already true, we flip enable False.
                        if ifstack[-1][0]:
                            if enable:
                                enable = False
                            elif not iftrigger:
                                # If False, but not triggered yet,
                                # we'll check expression.
                                if self.evalexpr(args):
                                    enable = True
                                    iftrigger = True

                    else:
                        self.error(
                            self.source,
                            dirtokens[0].lineno,
                            "Misplaced #elif"
                        )

                elif name == 'else':
                    if ifstack:
                        if ifstack[-1][0]:
                            if enable:
                                enable = False
                            elif not iftrigger:
                                enable = iftrigger = True
                    else:
                        self.error(
                            self.source,
                            dirtokens[0].lineno,
                            "Misplaced #else"
                        )

                elif name == 'endif':
                    if ifstack:
                        enable, iftrigger = ifstack.pop()
                    else:
                        self.error(
                            self.source,
                            dirtokens[0].lineno,
                            "Misplaced #endif"
                        )
                else:
                    # Unknown preprocessor directive
                    pass

            else:
                # Normal text
                if enable:
                    chunk.extend(l)

        for tok in self.expand_macros(chunk):
            yield tok

    def include(self, tokens):
        """ Implementation of file-inclusion.
        """
        # Try to extract the filename and then process an include file

        if tokens:
            # cache
            temp_path = self.temp_path
            t0 = tokens[0]

            if t0.value != '<' and t0.type != self.t_STRING:
                tokens = self.expand_macros(tokens)

            if t0.value == '<':
                # Include <...>
                for i, t in enumerate(tokens):
                    if t.value == ">":
                        break
                else:
                    print("Malformed #include <...>")
                filename = "".join(x.value for x in tokens[1:i])
                path = self.path + [""] + temp_path
            elif t0.type == self.t_STRING:
                filename = t0.value[1:-1]
                path = temp_path + [""] + self.path
            else:
                print("Malformed #include statement")
                return
        else:
            return

        for p in path:
            iname = join(p, filename)
            try:
                data = self.read_include_file(iname)
                dname = dirname(iname)
                if dname:
                    temp_path.insert(0, dname)
                for tok in self.parsegen(data, filename):
                    yield tok
                if dname:
                    del temp_path[0]
                break
            except IOError:
                pass
        else:
            print("Couldn't find '%s'" % filename)

    read_include_file = staticmethod(read_include_file)

    def define(self, tokens):
        """ Define a new macro.
        """
        if isinstance(tokens, STRING_TYPES):
            tokens = self.tokenize(tokens)

        linetok = tokens
        try:
            name = linetok[0]
            if len(linetok) > 1:
                mtype = linetok[1]
            else:
                mtype = None
            if not mtype:
                m = Macro(name.value, [])
            elif mtype.type in self.t_WS:
                # A normal macro
                m = Macro(name.value, self.tokenstrip(linetok[2:]))
            elif mtype.value == '(':
                # A macro with arguments
                tokcount, args, __ = self.collect_args(linetok[1:])
                variadic = False
                for a in args:
                    if variadic:
                        print("No more arguments"
                              " may follow a variadic argument"
                        )
                        return
                    astr = "".join([str(_i.value) for _i in a])
                    if astr == "...":
                        variadic = True
                        a[0].type = self.t_ID
                        a[0].value = '__VA_ARGS__'
                        variadic = True
                        del a[1:]
                        continue
                    elif astr[-3:] == "..." and a[0].type == self.t_ID:
                        variadic = True
                        del a[1:]
                        # If, for some reason, "." is part of the identifier,
                        # strip off the name for
                        # the purposes of macro expansion
                        if a[0].value[-3:] == '...':
                            a[0].value = a[0].value[:-3]
                        continue
                    if len(a) > 1 or a[0].type != self.t_ID:
                        print("Invalid macro argument")
                        return

                mvalue = self.tokenstrip(linetok[1 + tokcount:])
                i = 0
                while i < (len(mvalue) - 1):
                    if (
                        mvalue[i].type in self.t_WS
                        and mvalue[i + 1].value == '##'
                    ):
                        del mvalue[i]
                        continue
                    elif (
                        mvalue[i].value == '##'
                        and mvalue[i + 1].type in self.t_WS
                    ):
                        del mvalue[i + 1]
                    i += 1

                m = Macro(
                    name.value,
                    mvalue,
                    [x[0].value for x in args],
                    variadic
                )
                self.macro_prescan(m)
            else:
                print("Bad macro definition")
                return
        except LookupError:
            print("Bad macro definition")
        else:
            self.macros[name.value] = m

    def undef(self, tokens):
        """ Undefine a macro.
        """
        name = tokens[0].value
        self.macros.pop(name, None)


    def parse(self, text, source = None, ignore = None):
        """ Parse input text.
        """
        self.ignore = ignore or {}
        self.parser = self.parsegen(text, source)

    def token(self):
        """ Method to return individual tokens.
        """
        # cache
        ignore = self.ignore

        for tok in iter(self.parser):
            if tok.type in ignore:
                continue
            return tok

        self.parser = None
        return None


if __name__ == '__main__':
    import ply.lex as lex
    lexer = lex.lex()

    # Run a preprocessor
    import sys
    with open(sys.argv[1]) as f:
        data = f.read()

    p = Preprocessor(lexer)
    p.parse(data, sys.argv[1])
    while True:
        tok = p.token()
        if not tok: break
        print(p.source, tok)
