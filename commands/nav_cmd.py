from __future__ import absolute_import, with_statement, print_function, division, unicode_literals
from commands.parsing import MutuallyExclusiveGroup, ParseArgument
import math
from tradedb import System, Station, TradeDB
from tradeexcept import TradeException

######################################################################
# Parser config

help='Calculate a route between two systems.'
name='nav'
epilog=None
wantsTradeDB=True
arguments = [
    ParseArgument('starting', help='System to start from', type=str),
    ParseArgument('ending', help='System to end at', type=str),
]
switches = [
    ParseArgument('--ly-per',
            help='Maximum light years per jump.',
            dest='maxLyPer',
            metavar='N.NN',
            type=float,
        ),
    ParseArgument('--avoid',
            help='Exclude a system from the route. If you specify a station, '
                 'the system that station is in will be avoided instead.',
            action='append',
            default=[],
        ),
    ParseArgument('--via',
            help='Require specified systems/stations to be en-route (in order).',
            action='append',
            metavar='PLACE[,PLACE,...]',
        ),
    ParseArgument('--stations', '-S',
            help='Include station details.',
            action='store_true',
        ),
]

######################################################################
# Helpers


class NoRouteError(TradeException):
    pass


######################################################################
# Perform query and populate result set

def run(results, cmdenv, tdb):
    from commands.commandenv import ResultRow

    srcSystem, dstSystem = cmdenv.origPlace, cmdenv.destPlace
    if isinstance(srcSystem, Station):
        srcSystem = srcSystem.system
    if isinstance(dstSystem, Station):
        dstSystem = dstSystem.system

    maxLyPer = cmdenv.maxLyPer or tdb.maxSystemLinkLy

    cmdenv.DEBUG0("Route from {} to {} with max {}ly per jump.",
                    srcSystem.name(), dstSystem.name(), maxLyPer)

    # Build a list of src->dst pairs
    hops = [ [ srcSystem, None ] ]
    if cmdenv.viaPlaces:
        for hop in cmdenv.viaPlaces:
            hops[0][1] = hop
            hops.insert(0, [hop, None])
    hops[0][1] = dstSystem

    avoiding = [
        avoid for avoid in cmdenv.avoidPlaces
        if isinstance(avoid, System)
    ]

    route = [ ]
    for hop in hops:
        hopRoute = tdb.getRoute(hop[0], hop[1], maxLyPer, avoiding)
        if not hopRoute:
            raise NoRouteError(
                    "No route found between {} and {} "
                    "with a max {}ly/jump limit.".format(
                        hop[0].name(), hop[1].name(),
                        maxLyPer,
            ))
        route = route[:-1] + hopRoute

    results.summary = ResultRow(
                fromSys=srcSystem,
                toSys=dstSystem,
                maxLy=maxLyPer,
            )

    lastSys, totalLy, dirLy = srcSystem, 0.00, 0.00

    if cmdenv.stations:
        stationIDs = ",".join([
                ",".join(str(stn.ID) for stn in sys.stations)
                for sys in route
                if sys.stations
        ])
        stmt = """
                SELECT  si.station_id,
                        JULIANDAY('NOW') - JULIANDAY(MIN(si.modified))
                  FROM  StationItem AS si
                 WHERE  si.station_id IN ({})
                 GROUP  BY 1
                """.format(stationIDs)
        cmdenv.DEBUG0("Fetching ages: {}", stmt)
        ages = {}
        for ID, age in tdb.query(stmt):
            ages[ID] = age

    for (jumpSys, dist) in route:
        jumpLy = math.sqrt(lastSys.distToSq(jumpSys))
        totalLy += jumpLy
        if cmdenv.detail:
            dirLy = math.sqrt(jumpSys.distToSq(dstSystem))
        row = ResultRow(
                action='Via',
                system=jumpSys,
                jumpLy=jumpLy,
                totalLy=totalLy,
                dirLy=dirLy,
                )
        row.stations = []
        if cmdenv.stations:
            for (station) in jumpSys.stations:
                try:
                    age = "{:7.2f}".format(ages[station.ID])
                except:
                    age = "-"
                rr = ResultRow(
                        station=station,
                        age=age,
                )
                row.stations.append(rr)
        results.rows.append(row)
        lastSys = jumpSys
    results.rows[0].action='Depart'
    results.rows[-1].action='Arrive'

    return results

######################################################################
# Transform result set into output

def render(results, cmdenv, tdb):
    from formatting import RowFormat, ColumnFormat

    if cmdenv.quiet > 1:
        print(','.join(row.system.name() for row in results.rows))
        return

    longestNamed = max(results.rows,
                    key=lambda row: len(row.system.name()))
    longestNameLen = len(longestNamed.system.name())

    rowFmt = RowFormat()
    if cmdenv.detail:
        rowFmt.addColumn("Action", '<', 6, key=lambda row: row.action)
    rowFmt.addColumn("System", '<', longestNameLen,
            key=lambda row: row.system.name())
    rowFmt.addColumn("JumpLy", '>', '7', '.2f',
            key=lambda row: row.jumpLy)
    if cmdenv.detail:
        rowFmt.addColumn("Stations", '>', 2, 
            key=lambda row: len(row.system.stations))
    if cmdenv.detail:
        rowFmt.addColumn("DistLy", '>', '7', '.2f',
            key=lambda row: row.totalLy)
    if cmdenv.detail > 1:
        rowFmt.addColumn("DirLy", '>', 7, '.2f',
            key=lambda row: row.dirLy)

    showStations = cmdenv.stations
    if showStations:
        stnRowFmt = RowFormat(prefix='  /  ').append(
                ColumnFormat("Station", '<', 32,
                    key=lambda row: row.station.str())
        ).append(
                ColumnFormat("StnLs", '>', '10',
                    key=lambda row: row.station.distFromStar())
        ).append(
                ColumnFormat("Age/days", '>', 7,
                        key=lambda row: row.age)
        ).append(
                ColumnFormat("BMkt", '>', '4',
                    key=lambda row: \
                        TradeDB.marketStates[row.station.blackMarket])
        ).append(
                ColumnFormat("Pad", '>', '3',
                    key=lambda row: \
                        TradeDB.padSizes[row.station.maxPadSize])
        )
        if cmdenv.detail > 1:
            stnRowFmt.append(
                ColumnFormat("Itms", ">", 4,
                    key=lambda row: row.station.itemCount)
            )

    if not cmdenv.quiet:
        heading, underline = rowFmt.heading()
        if showStations:
            print(heading)
            heading, underline = stnRowFmt.heading()
        print(heading, underline, sep='\n')

    for row in results.rows:
        print(rowFmt.format(row))
        for stnRow in row.stations:
            print(stnRowFmt.format(stnRow))

    return results

