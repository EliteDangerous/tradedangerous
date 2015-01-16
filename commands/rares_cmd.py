from __future__ import absolute_import, with_statement, print_function, division, unicode_literals
from commands.commandenv import ResultRow
from commands.exceptions import *
from commands.parsing import MutuallyExclusiveGroup, ParseArgument
from formatting import RowFormat, ColumnFormat
from tradedb import TradeDB

import math

######################################################################
# Parser config

# Displayed on the "trade.py --help" command list, etc.
help='Find rares near your current local.'
# Should match the name of the module minus the _cmd.py
name='rares'
# Displayed at the end of the "trade.py rares --help"
epilog=None
# Set to False in commands that need to operate without
# a trade database.
wantsTradeDB=True
# Required parameters
arguments = [
    ParseArgument(
            'near',
            help='Your current system.',
            type=str,
            metavar='SYSTEMNAME',
    ),
]
# Optional parameters
switches = [
    ParseArgument('--ly',
            help='Maximum distance to search.',
            metavar='LY',
            type=float,
            default=180,
            dest='maxLyPer',
    ),
    ParseArgument('--limit',
            help='Maximum number of results to list.',
            default=None,
            type=int,
    ),
    ParseArgument('--pad-size', '-p',
            help='Limit the padsize to this ship size (S,M,L or ? for unkown).',
            metavar='PADSIZES',
            dest='padSize',
    ),
    ParseArgument('--price-sort', '-P',
            help='(When using --near) Sort by price not distance',
            action='store_true',
            default=False,
            dest='sortByPrice',
    ),
    ParseArgument('--reverse', '-r',
            help='Reverse the list.',
            action='store_true',
            default=False,
    ),
]

######################################################################
# Perform query and populate result set

def run(results, cmdenv, tdb):
    """
    Fetch all the data needed to display the results of a "rares"
    command. Does not actually print anything.

    Command execution is broken into two steps:
        1. cmd.run(results, cmdenv, tdb)
            Gather all the data required but generate no output,
        2. cmd.render(results, cmdenv, tdb)
            Print output to the user.

    This separation of concerns allows modularity; you can write
    a command that calls another command to fetch data for you
    and knowing it doesn't generate any output. Then you can
    process the data and return it and let the command parser
    decide when to turn it into output.

    It also opens a future door to commands that can present
    their data in a GUI as well as the command line by having
    a custom render() function.

    Parameters:
        results
            An object to be populated and returned
        cmdenv
            A CommandEnv object populated with the parameters
            for the command.
        tdb
            A TradeDB object to query against.

    Returns:
        None
            End execution without any output
        results
            Proceed to "render" with the output.
    """

    # Lookup the system we're currently in.
    start = cmdenv.nearSystem
    # Hoist the padSize parameter for convenience
    padSize = cmdenv.padSize

    # Start to build up the results data.
    results.summary = ResultRow()
    results.summary.near = start
    results.summary.ly = cmdenv.maxLyPer

    # The last step in calculating the distance between two
    # points is to perform a square root. However, we can avoid
    # the cost of doing this by squaring the distance we need
    # to check and only 'rooting values that are <= to it.
    maxLySq = cmdenv.maxLyPer ** 2

    # Look through the rares list.
    for rare in tdb.rareItemByID.values():
        if padSize:     # do we care about pad size?
            if not rare.station.checkPadSize(padSize):
                continue
        # Find the un-sqrt'd distance to the system.
        distSq = start.distToSq(rare.station.system)
        if maxLySq > 0: # do we have a limit on distance?
            if distSq > maxLySq:
                continue

        # Create a row for this item
        row = ResultRow()
        row.rare = rare
        row.dist = math.sqrt(distSq)
        results.rows.append(row)

    # Was anything matched?
    if not results:
        print("No matches found.")
        return None

    if cmdenv.sortByPrice:
        results.rows.sort(key=lambda row: row.dist)
        results.rows.sort(key=lambda row: row.rare.costCr, reverse=True)
    else:
        results.rows.sort(key=lambda row: row.rare.costCr, reverse=True)
        results.rows.sort(key=lambda row: row.dist)

    if cmdenv.reverse:
        results.rows.reverse()

    limit = cmdenv.limit or 0
    if limit > 0:
        results.rows = results.rows[:limit]

    return results

#######################################################################
## Transform result set into output

def render(results, cmdenv, tdb):
    """
    If the "run" command returned a result set and we are running
    from the command line, this function will be called to generate
    the output of the command.
    """

    if not results.rows:
        raise CommandLineError("No items found.")

    # Calculate the longest station name in our list.
    longestStnName = max(results.rows, key=lambda result: len(result.rare.station.name())).rare.station
    longestStnNameLen = len(longestStnName.name())
    longestRareName = max(results.rows, key=lambda result: len(result.rare.dbname)).rare
    longestRareNameLen = len(longestRareName.dbname)

    # Use the formatting system to describe what our
    # output rows are going to look at (see formatting.py)
    rowFmt = RowFormat()
    rowFmt.addColumn('Station', '<', longestStnNameLen,
            key=lambda row: row.rare.station.name())
    rowFmt.addColumn('Rare', '<', longestRareNameLen,
            key=lambda row: row.rare.name())
    rowFmt.addColumn('Cost', '>', 10, 'n',
            key=lambda row: row.rare.costCr)
    rowFmt.addColumn('DistLy', '>', 6, '.2f',
            key=lambda row: row.dist)
    rowFmt.addColumn('Alloc', '>', 6, 'n',
            key=lambda row: row.rare.maxAlloc)
    rowFmt.addColumn("StnLs", '>', 10,
            key=lambda row: row.rare.station.distFromStar())
    rowFmt.addColumn('B/mkt', '>', 4,
            key=lambda row: \
                    TradeDB.marketStates[row.rare.station.blackMarket]
    )
    rowFmt.addColumn("Pad", '>', '3',
            key=lambda row: \
                    TradeDB.padSizes[row.rare.station.maxPadSize]
    )

    # Print a heading summary if the user didn't use '-q'
    if not cmdenv.quiet:
        heading, underline = rowFmt.heading()
        print(heading, underline, sep='\n')

    # Print out our results.
    for row in results.rows:
        print(rowFmt.format(row))
