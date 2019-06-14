import sys

from .lex import LexToken
from .yacc import YaccSymbol

def iter_tokens(root):
    "Iterates over tokens in parse tree."

    if isinstance(root, LexToken):
        yield root
    else:
        if isinstance(root, YaccSymbol):
            children = root.value
        else: # root is a container
            children = root

        for child in children:
            for tok in iter_tokens(child):
                yield tok

if sys.version_info[0] == 2:
    def u2s(u):
        return u.encode("utf-8")
else:
    def u2s(u):
        return u

def adapt_for_label(s):
    # \\l - for left justification
    return s.\
        replace("\\", "\\\\").\
        replace('\n', "\\\\n\\l").\
        replace(" ", u2s(u"\u2423")).\
        replace("\t", "\\\\t")

def build_subtree(graph, current):
    node = "%s_%x" % (current.type, id(current))

    if isinstance(current, LexToken):
        label = current.type + "\\n" + adapt_for_label(current.prefix + current.value) + "\\l"
        graph.node(node, label=label)
    elif isinstance(current, YaccSymbol):
        graph.node(node, label=current.type)
        for child in current.value:
            graph.edge(node, build_subtree(graph, child))

    return node