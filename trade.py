#!/usr/bin/env python
#---------------------------------------------------------------------
# Copyright (C) Oliver 'kfsone' Smith 2014 <oliver@kfs.org>:
#  You are free to use, redistribute, or even print and eat a copy of
#  this software so long as you include this copyright notice.
#  I guarantee there is at least one bug neither of us knew about.
#---------------------------------------------------------------------
# TradeDangerous :: Command Line App :: Main Module
#
# TradeDangerous is a powerful set of tools for traders in Frontier
# Development's game "Elite: Dangerous". It's main function is
# calculating the most profitable trades between either individual
# stations or working out "profit runs".
#
# I wrote TD because I realized that the best trade run - in terms
# of the "average profit per stop" was rarely as simple as going
# Chango -> Dahan -> Chango.
#
# E:D's economy is complex; sometimes you can make the most profit
# by trading one item A->B and flying a second item B->A.
# But more often you need to fly multiple stations, especially since
# as you are making money different trade options are coming into
# your affordable range.
#
# END USERS: If you are a user looking to find out how to use TD,
# please consult the file "README.txt".
#
# DEVELOPERS: If you are a programmer who wants TD to do something
# cool, please see the TradeDB and TradeCalc modules. TD is designed
# to empower other programmers to do cool stuff.


######################################################################
# Imports

import argparse             # For parsing command line args.
import sys                  # Inevitably.
import time
import pathlib              # For path
import os
import math

######################################################################
# The thing I hate most about Python is the global lock. What kind
# of idiot puts globals in their programs?
import errno

args = None
originStation, finalStation = None, None
# Things not to do, places not to go, people not to see.
avoidItems, avoidSystems, avoidStations = [], [], []
# Stations we need to visit
viaStations = set()
originName, destName = "Any", "Any"
origins = []
maxUnits = 0

# Multi-function display, optional
mfd = None

######################################################################
# Database and calculator modules.

from tradeexcept import TradeException
from tradedb import TradeDB, AmbiguityError
from tradecalc import Route, TradeCalc, localedNo

tdb = None

######################################################################
# Helpers

class CommandLineError(TradeException):
    """
        Raised when you provide invalid input on the command line.
        Attributes:
            errorstr       What to tell the user.
    """
    def __init__(self, errorStr):
        self.errorStr = errorStr
    def __str__(self):
        return 'Error in command line: {}'.format(self.errorStr)


class NoDataError(TradeException):
    """
        Raised when a request is made for which no data can be found.
        Attributes:
            errorStr        Describe the problem to the user.
    """
    def __init__(self, errorStr):
        self.errorStr = errorStr
    def __str__(self):
        return "Error: {}\n".format(self.errorStr) + \
        "This can happen if you have not yet entered any price data for the station(s) involved, " + \
            "if there are no profitable trades between them, " + \
            "or the items are marked as 'n/a' (did you use '-zero' when updating?).\n" + \
        "See 'trade.py update -h' for help entering prices, or obtain a '.prices' file from the interwebs.\n" + \
        "Or see https://bitbucket.org/kfsone/tradedangerous/wiki/Price%20Data for more help.\n"


class HelpAction(argparse.Action):
    """
        argparse action helper for printing the argument usage,
        because Python 3.4's argparse is ever so subtly very broken.
    """
    def __call__(self, parser, namespace, values, option_string=None):
        parser.print_help()
        sys.exit(0)


class EditAction(argparse.Action):
    """
        argparse action that stores a value and also flags args._editing
    """
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, "_editing", True)
        setattr(namespace, self.dest, values or self.default)


class EditActionStoreTrue(argparse.Action):
    """
        argparse action that stores True but also flags args._editing
    """
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("nargs not allowed")
        super(EditActionStoreTrue, self).__init__(option_strings, dest, nargs=0, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, "_editing", True)
        setattr(namespace, self.dest, True)


def new_file_arg(string):
    """ argparse action handler for specifying a file that does not already exist. """

    path = pathlib.Path(string)
    if not path.exists(): return path
    sys.stderr.write("ERROR: Specified file, \"{}\", already exists.\n".format(path))
    sys.exit(errno.EEXIST)


class ParseArgument(object):
    """
        Provides argument forwarding so that 'makeSubParser' can take function-like arguments.
    """
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs


def makeSubParser(subparsers, name, help, commandFunc, arguments=None, switches=None, epilog=None):
    """
        Provide a normalized sub-parser for a specific command. This helps to
        make it easier to keep the command lines consistent and makes the calls
        to build them easier to write/read.
    """

    subParser = subparsers.add_parser(name, help=help, add_help=False, epilog=epilog)

    def addArguments(group, options, required, topGroup=None):
        """
            Registers a list of options to the specified group. Nodes
            are either an instance of ParseArgument or a list of
            ParseArguments. The list form is considered to be a
            mutually exclusive group of arguments.
        """

        for option in options:
            # lists indicate mutually exclusive subgroups
            if isinstance(option, list):
                addArguments((topGroup or group).add_mutually_exclusive_group(), option, required, topGroup=group)
            else:
                assert not required in option.kwargs
                if option.args[0][0] == '-':
                    group.add_argument(*(option.args), required=required, **(option.kwargs))
                else:
                    group.add_argument(*(option.args), **(option.kwargs))

    if arguments:
        argParser = subParser.add_argument_group('Required Arguments')
        addArguments(argParser, arguments, True)

    switchParser = subParser.add_argument_group('Optional Switches')
    switchParser.add_argument('-h', '--help', help='Show this help message and exit.', action=HelpAction, nargs=0)
    addArguments(switchParser, switches, False)

    subParser.set_defaults(proc=commandFunc)

    return subParser


######################################################################
# Checklist functions

def doStep(stepNo, action, detail=None, extra=None):
    stepNo += 1
    if mfd:
        mfd.display("#%d %s" % (stepNo, action), detail or "", extra or "")
    input("   %3d: %s: " % (stepNo, " ".join([item for item in [action, detail, extra] if item])))
    return stepNo


def note(str, addBreak=True):
    print("(i) %s (i)" % str)
    if addBreak:
        print()


def doChecklist(route, credits):
    stepNo, gainCr = 0, 0
    stations, hops, jumps = route.route, route.hops, route.jumps
    lastHopIdx = len(stations) - 1

    title = "(i) BEGINNING CHECKLIST FOR %s (i)" % route.str()
    underline = '-' * len(title)

    print(title)
    print(underline)
    print()
    if args.detail:
        print(route.summary())
        print()

    for idx in range(lastHopIdx):
        hopNo = idx + 1
        cur, nxt, hop = stations[idx], stations[idx + 1], hops[idx]

        # Tell them what they need to buy.
        if args.detail:
            note("HOP %d of %d" % (hopNo, lastHopIdx))

        note("Buy at %s" % cur.name())
        for (trade, qty) in sorted(hop[0], key=lambda tradeOption: tradeOption[1] * tradeOption[0].gainCr, reverse=True):
            stepNo = doStep(stepNo, 'Buy %d x' % qty, trade.name(), '@ %scr' % localedNo(trade.costCr))
        if args.detail:
            stepNo = doStep(stepNo, 'Refuel')
        print()

        # If there is a next hop, describe how to get there.
        note("Fly %s" % " -> ".join([ jump.name() for jump in jumps[idx] ]))
        if idx < len(hops) and jumps[idx]:
            for jump in jumps[idx][1:]:
                stepNo = doStep(stepNo, 'Jump to', '%s' % (jump.name()))
        if args.detail:
            stepNo = doStep(stepNo, 'Dock at', '%s' % nxt.str())
        print()

        note("Sell at %s" % nxt.name())
        for (trade, qty) in sorted(hop[0], key=lambda tradeOption: tradeOption[1] * tradeOption[0].gainCr, reverse=True):
            stepNo = doStep(stepNo, 'Sell %s x' % localedNo(qty), trade.name(), '@ %scr' % localedNo(trade.costCr + trade.gainCr))
        print()

        gainCr += hop[1]
        if args.detail and gainCr > 0:
            note("GAINED: %scr, CREDITS: %scr" % (localedNo(gainCr), localedNo(credits + gainCr)))

        if hopNo < lastHopIdx:
            print()
            print("--------------------------------------")
            print()

    if mfd:
        mfd.display('FINISHED', "+%scr" % localedNo(gainCr), "=%scr" % localedNo(credits + gainCr))
        mfd.attention(3)
        time.sleep(1.5)


######################################################################
# "run" command functionality.

def parseAvoids(args):
    """
        Process a list of avoidances.
    """

    global avoidItems, avoidSystems, avoidStations

    avoidances = args.avoid

    # You can use --avoid to specify an item, system or station.
    # and you can group them together with commas or list them
    # individually.
    for avoid in ','.join(avoidances).split(','):
        # Is it an item?
        item, system, station = None, None, None
        try:
            item = tdb.lookupItem(avoid)
            avoidItems.append(item)
            if TradeDB.normalizedStr(item.name()) == TradeDB.normalizedStr(avoid):
                continue
        except LookupError:
            pass
        # Is it a system perhaps?
        try:
            system = tdb.lookupSystem(avoid)
            avoidSystems.append(system)
            if TradeDB.normalizedStr(system.str()) == TradeDB.normalizedStr(avoid):
                continue
        except LookupError:
            pass
        # Or perhaps it is a station
        try:
            station = tdb.lookupStationExplicitly(avoid)
            if (not system) or (station.system is not system):
                avoidSystems.append(station.system)
                avoidStations.append(station)
            if TradeDB.normalizedStr(station.str()) == TradeDB.normalizedStr(avoid):
                continue
        except LookupError as e:
            pass

        # If it was none of the above, whine about it
        if not (item or system or station):
            raise CommandLineError("Unknown item/system/station: %s" % avoid)

        # But if it matched more than once, whine about ambiguity
        if item and system: raise AmbiguityError('Avoidance', avoid, item, system.str())
        if item and station: raise AmbiguityError('Avoidance', avoid, item, station.str())
        if system and station and station.system != system: raise AmbiguityError('Avoidance', avoid, system.str(), station.str())

    if args.debug:
        print("Avoiding items %s, systems %s, stations %s" % (
            [ item.name() for item in avoidItems ],
            [ system.name() for system in avoidSystems ],
            [ station.name() for station in avoidStations ]
        ))


def parseVias(args):
    """
        Process a list of station names and build them into a
        list of waypoints for the route.
    """

    # accept [ "a", "b,c", "d" ] by joining everything and then splitting it.
    global viaStations

    for via in ",".join(args.via).split(","):
        station = tdb.lookupStation(via)
        if station.itemCount == 0:
            raise NoDataError("No price data available for via station {}.".format(station.name()))
        viaStations.add(station)


def processRunArguments(args):
    """
        Process arguments to the 'run' option.
    """

    global origins, originStation, finalStation, maxUnits, originName, destName, mfd, unspecifiedHops

    if args.credits < 0:
        raise CommandLineError("Invalid (negative) value for initial credits")
    # I'm going to allow 0 credits as a future way of saying "just fly"

    if args.routes < 1:
        raise CommandLineError("Maximum routes has to be 1 or higher")
    if args.routes > 1 and args.checklist:
        raise CommandLineError("Checklist can only be applied to a single route.")

    if args.hops < 1:
        raise CommandLineError("Minimum of 1 hop required")
    if args.hops > 64:
        raise CommandLineError("Too many hops without more optimization")

    if args.maxJumpsPer < 0:
        raise CommandLineError("Negative jumps: you're already there?")

    if args.origin:
        originName = args.origin
        originStation = tdb.lookupStation(originName)
        origins = [ originStation ]
    else:
        origins = [ station for station in tdb.stationByID.values() ]

    if args.dest:
        destName = args.dest
        finalStation = tdb.lookupStation(destName)
        if args.hops == 1 and originStation and finalStation and originStation == finalStation:
            raise CommandLineError("More than one hop required to use same from/to destination")

    if args.avoid:
        parseAvoids(args)
    if args.via:
        parseVias(args)

    unspecifiedHops = args.hops + (0 if originStation else 1) - (1 if finalStation else 0)
    if len(viaStations) > unspecifiedHops:
        raise CommandLineError("Too many vias: {} stations vs {} hops available.".format(len(viaStations), unspecifiedHops))

    # If the user specified a ship, use it to fill out details unless
    # the user has explicitly supplied them. E.g. if the user says
    # --ship sidewinder --capacity 2, use their capacity limit.
    if args.ship:
        ship = tdb.lookupShip(args.ship)
        args.ship = ship
        if args.capacity is None: args.capacity = ship.capacity
        if args.maxLyPer is None: args.maxLyPer = ship.maxLyFull
    if args.capacity is None:
        raise CommandLineError("Missing '--capacity' or '--ship' argument")
    if args.maxLyPer is None:
        raise CommandLineError("Missing '--ly-per' or '--ship' argument")
    if args.capacity < 0:
        raise CommandLineError("Invalid (negative) cargo capacity")
    if args.capacity > 1000:
        raise CommandLineError("Capacity > 1000 not supported (you specified %s)" % args.capacity)

    if args.limit and args.limit > args.capacity:
        raise CommandLineError("'limit' must be <= capacity")
    if args.limit and args.limit < 0:
        raise CommandLineError("'limit' can't be negative, silly")
    maxUnits = args.limit if args.limit else args.capacity

    arbitraryInsuranceBuffer = 42
    if args.insurance and args.insurance >= (args.credits + arbitraryInsuranceBuffer):
        raise CommandLineError("Insurance leaves no margin for trade")

    if args.unique and args.hops >= len(tdb.stationByID):
        raise CommandLineError("Requested unique trip with more hops than there are stations...")
    if args.unique:
        if ((originStation and originStation == finalStation) or
                (originStation and originStation in viaStations) or
                 (finalStation and finalStation in viaStations)):
            raise CommandLineError("from/to/via repeat conflicts with --unique")

    if originStation and originStation.itemCount == 0:
        raise NoDataError("Start station {} doesn't have any price data.".format(originStation.name()))
    if finalStation and finalStation.itemCount == 0:
        raise NoDataError("End station {} doesn't have any price data.".format(finalStation.name()))
    if finalStation and args.hops == 1 and originStation and not finalStation in originStation.tradingWith:
        raise CommandLineError("No profitable items found between {} and {}".format(originStation.name(), finalStation.name()))
    if originStation and len(originStation.tradingWith) == 0:
        raise NoDataError("No data found for potential buyers for items from {}.".format(originStation.name()))

    if args.x52pro:
        from mfd import X52ProMFD
        mfd = X52ProMFD()


def runCommand(args):
    """ Calculate trade runs. """

    global tdb

    if args.debug: print("# 'run' mode")

    if tdb.tradingCount == 0:
        raise NoDataError("Database does not contain any profitable trades.")

    processRunArguments(args)

    startCr = args.credits - args.insurance
    routes = [
        Route(stations=[src], hops=[], jumps=[], startCr=startCr, gainCr=0)
        for src in origins
        if not (src in avoidStations or src.system in avoidSystems)
    ]
    numHops = args.hops
    lastHop = numHops - 1
    viaStartPos = 1 if originStation else 0

    if args.debug or args.detail:
        summaries = [ 'With {}cr'.format(localedNo(args.credits)) ]
        summaries += [ 'From {}'.format(originStation.str() if originStation else 'Anywhere') ]
        summaries += [ 'To {}'.format(finalStation.str() if finalStation else 'Anywhere') ]
        if viaStations: summaries += [ 'Via {}'.format(', '.join([ station.str() for station in viaStations ])) ]
        print(*summaries, sep=' / ')
        print("%d cap, %d hops, max %d jumps/hop and max %0.2f ly/jump" % (args.capacity, numHops, args.maxJumpsPer, args.maxLyPer))
        print()

    # Instantiate the calculator object
    calc = TradeCalc(tdb, debug=args.debug, capacity=args.capacity, maxUnits=maxUnits, margin=args.margin, unique=args.unique)

    # Build a single list of places we want to avoid
    # TODO: Keep these seperate because we wind up spending
    # time breaking the list down in getDestinations.
    avoidPlaces = avoidSystems + avoidStations

    if args.debug: print("unspecified hops {}, numHops {}, viaStations {}".format(unspecifiedHops, numHops, len(viaStations)))
    for hopNo in range(numHops):
        if mfd:
            mfd.display('TradeDangerous', 'CALCULATING', 'Hop {}'.format(hopNo))
        if calc.debug: print("# Hop %d" % hopNo)

        restrictTo = None
        if hopNo == lastHop and finalStation:
            restrictTo = set([finalStation])
            ### TODO:
            ### if hopsLeft < len(viaStations):
            ###   ... only keep routes that include len(viaStations)-hopsLeft routes
            ### Thus: If you specify 5 hops via a,b,c and we are on hop 3, only keep
            ### routes that include a, b or c. On hop 4, only include routes that
            ### already include 2 of the vias, on hop 5, require all 3.
            if viaStations:
                routes = [ route for route in routes if viaStations & set(route.route[viaStartPos:]) ]
        elif unspecifiedHops == len(viaStations):
            # Everywhere we're going is in the viaStations list.
            restrictTo = viaStations

        routes = calc.getBestHops(routes, startCr,
                                  restrictTo=restrictTo, avoidItems=avoidItems, avoidPlaces=avoidPlaces,
                                  maxJumpsPer=args.maxJumpsPer, maxLyPer=args.maxLyPer)

    if viaStations:
        routes = [ route for route in routes if viaStations & set(route.route[viaStartPos:]) ]

    if not routes:
        print("No routes matched your critera, or price data for that route is missing.")
        return

    routes.sort()

    for i in range(0, min(len(routes), args.routes)):
        print(routes[i].detail(detail=args.detail))

    # User wants to be guided through the route.
    if args.checklist:
        assert args.routes == 1
        doChecklist(routes[0], args.credits)


######################################################################
# "update" command functionality.

def getEditorPaths(args, editorName, envVar, windowsFolders, winExe, nixExe):
    if args.debug: print("# Locating {} editor".format(editorName))
    try:
        return os.environ[envVar]
    except KeyError: pass

    paths = []

    import platform
    system = platform.system()
    if system == 'Windows':
        binary = winExe
        for folder in ["Program Files", "Program Files (x86)"]:
            for version in windowsFolders:
                paths.append("{}\\{}\\{}".format(os.environ['SystemDrive'], folder, version))
    else:
        binary = nixExe

    try:
        paths += os.environ['PATH'].split(os.pathsep)
    except KeyError: pass

    for path in paths:
        candidate = os.path.join(path, binary)
        try:
            if pathlib.Path(candidate).exists():
                return candidate
        except OSError:
            pass

    raise CommandLineError("ERROR: Unable to locate {} editor.\nEither specify the path to your editor with --editor or set the {} environment variable to point to it.".format(editorName, envVar))


def editUpdate(args, stationID):
    """
        Dump the price data for a specific station to a file and
        launch the user's text editor to let them make changes
        to the file.

        If the user makes changes, re-load the file, update the
        database and regenerate the master .prices file.
    """

    if args.debug: print("# 'update' mode with editor. editor:{} station:{}".format(args.editor, args.station))

    import buildcache
    import prices
    import subprocess
    import os

    editor, editorArgs = args.editor, []
    if args.sublime:
        if args.debug: print("# Sublime mode")
        if not editor:
            editor = getEditorPaths(args, "sublime", "SUBLIME_EDITOR", ["Sublime Text 3", "Sublime Text 2"], "sublime_text.exe", "subl")
        editorArgs += [ "--wait" ]
    elif args.npp:
        if args.debug: print("# Notepad++ mode")
        if not editor:
            editor = getEditorPaths(args, "notepad++", "NOTEPADPP_EDITOR", ["Notepad++"], "notepad++.exe", "notepad++")
        if not args.quiet: print("NOTE: You'll need to exit Notepad++ to return control back to trade.py")
    elif args.vim:
        if args.debug: print("# VI iMproved mode")
        if not editor:
            # Hack... Hackity hack, hack, hack.
            # This has a disadvantage in that: we don't check for just "vim" (no .exe) under Windows
            vimDirs = [ "Git\\share\\vim\\vim{}".format(vimVer) for vimVer in range(70,75) ]
            editor = getEditorPaths(args, "vim", "EDITOR", vimDirs, "vim.exe", "vim")
    elif args.notepad:
        if args.debug: print("# Notepad mode")
        editor = "notepad.exe"  # herp

    try:
        envArgs = os.environ["EDITOR_ARGS"]
        if envArgs: editorArgs += envArgs.split(' ')
    except KeyError: pass

    # Create a temporary text file with a list of the price data.
    tmpPath = pathlib.Path("prices.tmp")
    if tmpPath.exists():
        print("ERROR: Temporary file ({}) already exists.".format(tmpPath))
        sys.exit(1)
    absoluteFilename = None
    try:
        # Open the file and dump data to it.
        with tmpPath.open("w") as tmpFile:
            # Remember the filename so we know we need to delete it.
            absoluteFilename = str(tmpPath.resolve())
            withModified = args.all # or args.timestamps
            withLevels   = args.all # or args.levels
            prices.dumpPrices(args.db, withModified=withModified, withLevels=withLevels, file=tmpFile, stationID=stationID, defaultZero=args.zero, debug=args.debug)

        # Stat the file so we can determine if the user writes to it.
        # Use the most recent create/modified timestamp.
        preStat = tmpPath.stat()
        preStamp = max(preStat.st_mtime, preStat.st_ctime)

        # Launch the editor
        editorCommandLine = [ editor ] + editorArgs + [ absoluteFilename ]
        if args.debug: print("# Invoking [{}]".format(' '.join(editorCommandLine)))
        try:
            result = subprocess.call(editorCommandLine)
        except FileNotFoundError:
            raise CommandLineError("Unable to launch specified editor: {}".format(editorCommandLine))
        if result != 0:
            print("NOTE: Edit failed ({}), nothing to import.".format(result))
            sys.exit(1)

        # Did they update the file? Some editors destroy the file and rewrite it,
        # other files just write back to it, and some OSes do weird things with
        # these timestamps. That's why we have to use both mtime and ctime.
        postStat = tmpPath.stat()
        postStamp = max(postStat.st_mtime, postStat.st_ctime)

        if postStamp == preStamp:
            import random
            print("- No changes detected - doing nothing. {}".format(random.choice([
                    "Brilliant!", "I'll get my coat.", "I ain't seen you.", "You ain't seen me", "... which was nice", "Bingo!", "Scorchio!", "Boutros, boutros, ghali!", "I'm Ed Winchester!", "Suit you, sir! Oh!"
                ])))
            sys.exit(0)

        if args.debug:
            print("# File changed - importing data.")

        buildcache.processPricesFile(db=tdb.getDB(), pricesPath=tmpPath, stationID=stationID, debug=args.debug)

        # If everything worked, we need to re-build the prices file.
        if args.debug:
            print("# Update complete, regenerating .prices file")

        with tdb.pricesPath.open("w") as pricesFile:
            prices.dumpPrices(args.db, withModified=True, withLevels=True, file=pricesFile, debug=args.debug)

        # Update the DB file so we don't regenerate it.
        pathlib.Path(args.db).touch()

    finally:
        # If we created the file, we delete the file.
        if absoluteFilename: tmpPath.unlink()


def updateCommand(args):
    """
        Allow the user to update the prices database.
    """

    station = tdb.lookupStation(args.station)
    stationID = station.ID

    if args.zero and not args.all:
        raise CommandLineError("TEMPORARY: --zero requires --all for the time being, just so you understand the connection.")

    if args._editing:
        # User specified one of the options to use an editor.
        return editUpdate(args, stationID)

    if args.debug: print('# guided "update" mode station:{}'.format(args.station))

    print("Guided mode not implemented yet. Try using --editor, --sublime or --notepad")


######################################################################
#

def lookupSystem(name, intent):
    """
        Look up a name using either a system or station name.
    """

    try:
        return tdb.lookupSystem(name)
    except LookupError:
        try:
            return tdb.lookupStationExplicitly(name).system
        except LookupError:
            raise CommandLineError("Unknown {} system/station, '{}'".format(intent, name))


def distanceAlongPill(sc, percent):
    """
        Estimate a distance along the Pill using 2 reference systems
    """
    sa = tdb.lookupSystem("Eranin")
    sb = tdb.lookupSystem("HIP 107457")
    dotProduct = (sb.posX-sa.posX) * (sc.posX-sa.posX) \
               + (sb.posY-sa.posY) * (sc.posY-sa.posY) \
               + (sb.posZ-sa.posZ) * (sc.posZ-sa.posZ)
    length = math.sqrt((sb.posX-sa.posX) * (sb.posX-sa.posX)
                     + (sb.posY-sa.posY) * (sb.posY-sa.posY)
                     + (sb.posZ-sa.posZ) * (sb.posZ-sa.posZ))
    if percent:
        return 100. * dotProduct / length / length

    return dotProduct / length

def localCommand(args):
    """
        Local systems
    """

    srcSystem = lookupSystem(args.system, 'system')

    if args.ship:
        ship = tdb.lookupShip(args.ship)
        args.ship = ship
        if args.ly is None: args.ly = (ship.maxLyFull if args.full else ship.maxLyEmpty)
    ly = args.ly or tdb.maxSystemLinkLy

    title = "Local systems to {} within {} ly.".format(srcSystem.name(), ly)
    print(title)
    print('-' * len(title))

    distances = { }

    for (destSys, destDist) in srcSystem.links.items():
        if args.debug:
            print("Checking {} dist={:5.2f}".format(destSys.str(), destDist))
        if destDist > ly:
            continue
        distances[destSys] = destDist

    for (system, dist) in sorted(distances.items(), key=lambda x: x[1]):
        pillLength = ""
        if args.pill or args.percent:
            pillLengthFormat = " [{:4.0f}%]" if args.percent else " [{:5.1f}]"
            pillLength = pillLengthFormat.format(distanceAlongPill(system, args.percent))
        print("{:5.2f}{} {}".format(dist, pillLength, system.str()))
        if args.detail:
            for (station) in system.stations:
                stationDistance = " {} ls".format(station.lsFromStar) if station.lsFromStar > 0 else ""
                print("\t<{}>{}".format(station.str(), stationDistance))

def navCommand(args):
    """
        Give player directions A->B
    """

    srcSystem = lookupSystem(args.start, 'start')
    dstSystem = lookupSystem(args.end, 'end')

    avoiding = []
    if args.ship:
        ship = tdb.lookupShip(args.ship)
        args.ship = ship
        if args.maxLyPer is None: args.maxLyPer = (ship.maxLyFull if args.full else ship.maxLyEmpty)
    maxLyPer = args.maxLyPer or tdb.maxSystemLinkLy

    if args.debug:
        print("# Route from {} to {} with max {} ly per jump.".format(srcSystem.name(), dstSystem.name(), maxLyPer))

    openList = { srcSystem: 0.0 }
    distances = { srcSystem: [ 0.0, None ] }

    # As long as the open list is not empty, keep iterating.
    while openList and not dstSystem in distances:
        # Expand the search domain by one jump; grab the list of
        # nodes that are this many hops out and then clear the list.
        openNodes, openList = openList, {}

        for (node, startDist) in openNodes.items():
            for (destSys, destDist) in node.links.items():
                if destDist > maxLyPer:
                    continue
                dist = startDist + destDist
                # If we already have a shorter path, do nothing
                try:
                    distNode = distances[destSys]
                    if distNode[0] <= dist:
                        continue
                    distNode[0], distNode[1] = dist, node
                except KeyError:
                    distances[destSys] = [ dist, node ]
                assert not destSys in openList or openList[destSys] > dist
                openList[destSys] = dist

    # Unravel the route by tracing back the vias.
    route = [ dstSystem ]
    try:
        while route[-1] != srcSystem:
            jumpEnd = route[-1]
            jumpStart = distances[jumpEnd][1]
            route.append(jumpStart)
    except KeyError:
        print("No route found between {} and {} with {}ly jump limit.".format(srcSystem.name(), dstSystem.name(), maxLyPer))
        return
    route.reverse()
    titleFormat = "From {src} to {dst} with {mly}ly per jump limit."
    if args.detail:
        labelFormat = "{act:<6} | {sys:<30} | {jly:<7} | {tly:<8}"
        stepFormat = "{act:<6} | {sys:<30} | {jly:>7.2f} | {tly:>8.2f}"
    elif not args.quiet:
        labelFormat = "{sys:<30} ({jly:<7})"
        stepFormat  = "{sys:<30} ({jly:>7.2f})"
    elif args.quiet == 1:
        titleFormat = "{src}->{dst} limit {mly}ly:"
        labelFormat = None
        stepFormat = " {sys}"
    else:
        titleFormat, labelFormat, stepFormat = None, None, "{sys}"

    if titleFormat:
        print(titleFormat.format(src=srcSystem.name(), dst=dstSystem.name(), mly=maxLyPer))

    if labelFormat:
        label = labelFormat.format(act='Action', sys='System', jly='Jump Ly', tly='Total Ly')
        print(label)
        print('-' * len(label))

    lastHop, totalLy = None, 0.00
    def present(action, system):
        nonlocal lastHop, totalLy
        jumpLy = system.links[lastHop] if lastHop else 0.00
        totalLy += jumpLy
        print(stepFormat.format(act=action, sys=system.name(), jly=jumpLy, tly=totalLy))
        lastHop = system

    present('Depart', srcSystem)
    for viaSys in route[1:-1]:
        present('Via', viaSys)
    present('Arrive', dstSystem)


######################################################################
# functionality for the "cleanup" command

def cleanupCommand(args):
    """
        Perform maintenance on the database.
    """

    global tdb

    if args.minutes <= 0:
        raise CommandLineError("Invalid --minutes specification.")

    if not args.quiet:
        print("* Performing database cleanup, expiring {} minute orphan records.{}".format(
                args.minutes,
                " DRY RUN." if args.dryRun else ""
            ))

    # Get access to the DB in a transaction so that if something goes
    # wrong or we are only doing a dry run, nothing will actually happen.
    db = tdb.getDB()
    db.isolation_level = None
    cur = db.execute("BEGIN")

    # How many prices were there before?
    beforeCount = cur.execute('SELECT COUNT(*) FROM Price').fetchone()[0]

    stmt = """
        SELECT OldPrice.item_id, OldPrice.station_id, OldPrice.modified, MIN(NewerPrice.modified)
         FROM Price as OldPrice
                INNER JOIN Price as NewerPrice
                    ON (OldPrice.station_id = NewerPrice.station_id
                        AND OldPrice.modified <= DATETIME(NewerPrice.modified, '-{} minute'))
        GROUP BY 1, 2
    """
    deletions = []
    for (itemID, stationID, oldTimestamp, newTimestamp) in cur.execute(stmt.format(args.minutes)):
        if args.dryRun or args.debug:
            item, station = tdb.itemByID[itemID], tdb.stationByID[stationID]
            print("- {} @ {} : {} vs {}".format(station.str(), item.name(), oldTimestamp, newTimestamp))
        deletions.append([itemID, stationID])
    if not deletions:
        if not args.quiet:
            print("* Nothing to do.")
        return None

    cur.executemany("DELETE FROM Price WHERE item_id = ? AND station_id = ?", deletions)

    # And how many after what we were doing?
    afterCount = cur.execute('SELECT COUNT(*) FROM Price').fetchone()[0]

    if args.debug or args.dryRun:
        print("# Price records before: {}, after: {}".format(beforeCount, afterCount))

    if not args.dryRun:
        deleted = len(deletions)
        if args.quiet < 2:
            print("- Removed {} {}.".format(deleted, "entry" if deleted == 1 else "entries"))
        db.execute("COMMIT")
    else:
        if args.quiet < 2:
            print("# DRY RUN: Database unmodified.")
        db.execute("ROLLBACK")  # technically this is redundant

    return deletions


######################################################################
# main entry point


def main():
    global args, tdb

    parser = argparse.ArgumentParser(description='Trade run calculator', add_help=False, epilog='For help on a specific command, use the command followed by -h.')
    parser.set_defaults(_editing=False)

    # Arguments common to all subparsers.
    commonArgs = parser.add_argument_group('Common Switches')
    commonArgs.add_argument('-h', '--help', help='Show this help message and exit.', action=HelpAction, nargs=0)
    commonArgs.add_argument('--debug',  '-w', help='Enable diagnostic output.', default=0, required=False, action='count')
    commonArgs.add_argument('--detail', '-v', help='Increase level  of detail in output.', default=0, required=False, action='count')
    commonArgs.add_argument('--quiet',  '-q', help='Reduce level of detail in output.', default=0, required=False, action='count')
    commonArgs.add_argument('--db', help='Specify location of the SQLite database. Default: {}'.format(TradeDB.defaultDB), type=str, default=str(TradeDB.defaultDB))
    commonArgs.add_argument('--cwd',    '-C', help='Change the directory relative to which TradeDangerous will try to access files such as the .db, etc.', type=str, required=False)

    subparsers = parser.add_subparsers(dest='subparser', title='Commands')

    # Maintenance on the database.
    cleanupParser = makeSubParser(subparsers, 'cleanup', 'Remove stale price data.', cleanupCommand,
        epilog='EMDN sometimes gets invalid data (either from Elite Dangerous UI issues or people deliberately submitting bad data). These items can be crudely detected by checking for price entries that are somewhat older than other entries for the same station.',
        switches = [
            ParseArgument('--minutes', help='Cull prices which are this much older than other prices for the same station.', type=int, default=30),
            ParseArgument('--dry-run', help="Show which records would be deleted, but don't actually delete anything.", dest='dryRun', default=False, action='store_true')
        ]
    )

    # "nav" tells you how to get from one place to another.
    navParser = makeSubParser(subparsers, 'nav', 'Calculate a route between two systems.', navCommand,
        arguments = [
            ParseArgument('start', help='System to start from', type=str),
            ParseArgument('end', help='System to end at', type=str),
        ],
        switches = [
            ParseArgument('--ship', help='Use the maximum jump distance of the specified ship (defaults to the empty value).', metavar='shiptype', type=str),
            ParseArgument('--full', help='(With --ship) Limits the jump distance to that of a full ship.', action='store_true', default=False),
            ParseArgument('--ly-per', help='Maximum light years per jump.', metavar='N.NN', type=float, dest='maxLyPer'),
        ]
    )

    # "local" shows systems local to given system.
    localParser = makeSubParser(subparsers, 'local', 'Calculate local systems.', localCommand,
        arguments = [
            ParseArgument('system', help='System to measure from', type=str),
        ],
        switches = [
            ParseArgument('--ship', help='Use the maximum jump distance of the specified ship (defaults to the empty value).', metavar='shiptype', type=str),
            ParseArgument('--full', help='(With --ship) Limits the jump distance to that of a full ship.', action='store_true', default=False),
            ParseArgument('--ly', help='Maximum light years to measure.', metavar='N.NN', type=float, dest='ly'),
            [
              ParseArgument('--pill', help='Show distance along the pill in ly.', action='store_true', default=False),
              ParseArgument('--percent', help='Show distance along pill as percentage.', action='store_true', default=False),
            ],
       ]
    )

    # "run" calculates a trade run.
    runParser = makeSubParser(subparsers, 'run', 'Calculate best trade run.', runCommand,
        arguments = [
            ParseArgument('--credits', help='Starting credits.', metavar='CR', type=int)
        ],
        switches = [
            ParseArgument('--ship', help='Set capacity and ly-per from ship type.', metavar='shiptype', type=str),
            ParseArgument('--capacity', help='Maximum capacity of cargo hold.', metavar='N', type=int),
            ParseArgument('--from', help='Starting system/station.', metavar='STATION', dest='origin'),
            ParseArgument('--to', help='Final system/station.', metavar='STATION', dest='dest'),
            ParseArgument('--via', help='Require specified systems/stations to be en-route.', metavar='PLACE[,PLACE,...]', action='append'),
            ParseArgument('--avoid', help='Exclude an item, system or station from trading. Partial matches allowed, e.g. "dom.App" or "domap" matches "Dom. Appliances".', action='append'),
            ParseArgument('--hops', help='Number of hops (station-to-station) to run.', metavar='N', type=int, default=2),
            ParseArgument('--jumps-per', help='Maximum number of jumps (system-to-system) per hop.', metavar='N', dest='maxJumpsPer', type=int, default=2),
            ParseArgument('--ly-per', help='Maximum light years per jump.', metavar='N.NN', type=float, dest='maxLyPer'),
            ParseArgument('--limit', help='Maximum units of any one cargo item to buy (0: unlimited).', metavar='N', type=int),
            ParseArgument('--unique', help='Only visit each station once.', action='store_true', default=False),
            ParseArgument('--margin', help='Reduce gains made on each hop to provide a margin of error for market fluctuations (e.g: 0.25 reduces gains by 1/4). 0<: N<: 0.25.', metavar='N.NN', type=float, default=0.00),
            ParseArgument('--insurance', help='Reserve at least this many credits to cover insurance.', metavar='CR', type=int, default=0),
            ParseArgument('--routes', help='Maximum number of routes to show. DEFAULT: 1', metavar='N', type=int, default=1),
            ParseArgument('--checklist', help='Provide a checklist flow for the route.', action='store_true', default=False),
            ParseArgument('--x52-pro', help='Enable experimental X52 Pro MFD output.', action='store_true', dest='x52pro', default=False),
        ]
    )

    # "update" provides the user a way to edit prices.
    updateParser = makeSubParser(subparsers, 'update', 'Update prices for a station.', updateCommand,
        epilog="Generates a human-readable version of the price list for a given station and opens it in the specified text editor.\n"
            "The format is intended to closely resemble the presentation of the market in-game. If you change the order items are listed in, "
            "the order will be kept for future edits, making it easier to quickly check for changes.",
        arguments = [
            ParseArgument('station', help='Name of the station to update.', type=str)
        ],
        switches = [
            ParseArgument('--editor', help='Generates a text file containing the prices for the station and loads it into the specified editor.', default=None, type=str, action=EditAction),
            ParseArgument('--all', help='Generates the temporary file with all columns and new timestamp.', action='store_true', default=False),
            ParseArgument('--zero', help='(with --all) Show "0" for unknown demand/stock values instead of "-1".', action='store_true', default=False),
            [   # Mutually exclusive group:
                ParseArgument('--sublime', help='Like --editor but uses Sublime Text (2 or 3), which is nice.', action=EditActionStoreTrue),
                ParseArgument('--notepad', help='Like --editor but uses Notepad.', action=EditActionStoreTrue),
                ParseArgument('--npp',     help='Like --editor but uses Notepad++.', action=EditActionStoreTrue),
                ParseArgument('--vim',     help='Like --editor but uses vim.', action=EditActionStoreTrue),
            ]
        ]
    )

    args = parser.parse_args()
    if not 'proc' in args:
        helpText = "No sub-command specified.\n" + parser.format_help() + "\nNote: As of v3 you need to specify one of the 'sub-commands' listed above (run, nav, etc)."
        raise CommandLineError(helpText)

    if args.detail and args.quiet:
        raise CommandLineError("'--detail' (-v) and '--quiet' (-q) are mutually exclusive.")

    # If a directory was specified, relocate to it.
    # Otherwise, try to chdir to 
    if args.cwd:
        os.chdir(args.cwd)
    else:
        if sys.argv[0]:
            cwdPath = pathlib.Path('.').resolve()
            exePath = pathlib.Path(sys.argv[0]).parent.resolve()
            if cwdPath != exePath:
                if args.debug: print("# cwd at launch was: {}, changing to {} to match trade.py".format(cwdPath, exePath))
                os.chdir(str(exePath))

    # load the database
    tdb = TradeDB(debug=args.debug, dbFilename=args.db)

    # run the commands
    return args.proc(args)


######################################################################


if __name__ == "__main__":
    try:
        main()
    except (TradeException) as e:
        print("%s: %s" % (sys.argv[0], str(e)))
    if mfd:
        mfd.finish()

