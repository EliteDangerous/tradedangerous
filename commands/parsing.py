from __future__ import absolute_import, with_statement, print_function, division, unicode_literals

######################################################################
# Parsing Helpers

class ParseArgument(object):
    """
        Provides argument forwarding so that 'makeSubParser' can take function-like arguments.
    """
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs


class MutuallyExclusiveGroup(object):
    def __init__(self, *args):
        self.arguments = list(args)
