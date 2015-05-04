from __future__ import absolute_import, with_statement, print_function, division, unicode_literals
from commands.parsing import MutuallyExclusiveGroup, ParseArgument
from commands.exceptions import *
import sqlite3
import math

######################################################################
# Parser config

help='Check item prices and report suspicious entries.'
name='checkprices'
epilog=None
wantsTradeDB=True
arguments = [
]
switches = [
]

######################################################################
# Helper

class StdDevFunc:
    """
    http://stackoverflow.com/questions/2298339/standard-deviation-for-sqlite/24423341#24423341
    For use as an aggregate function in SQLite
    """
    def __init__(self):
        self.M = 0.0
        self.S = 0.0
        self.k = 0

    def step(self, value):
        try:
            # automatically convert text to float, like the rest of SQLite
            val = float(value) # if fails, skips this iteration, which also ignores nulls
            tM = self.M
            self.k += 1
            self.M += ((val - tM) / self.k)
            self.S += ((val - tM) * (val - self.M))
        except:
            pass

    def finalize(self):
        if self.k < 2: # avoid division by zero
            return None
        else:
            return math.sqrt(self.S / (self.k-1))

def buildPriceSQL(stmtList):
    if len(stmtList) == 0:
        return ""
    else:
        return "({stmt})".format(stmt=" OR ".join(stmtList))

def buildPriceStmt(minPrice, maxPrice):
    if minPrice == maxPrice:
        return "(price = {})".format(minPrice)
    else:
        return "(price BETWEEN {} AND {})".format(minPrice, maxPrice)

######################################################################
# Perform query and populate result set

def run(results, cmdenv, tdb):
    from commands.commandenv import ResultRow

    # connect to the database
    conn = tdb.getDB()
    conn.row_factory = sqlite3.Row

    # install standard deviation function
    conn.create_aggregate("stddev", 1, StdDevFunc)

    # init
    checkCount  = cmdenv.detail
    itemCursor  = conn.cursor()
    checkCursor = conn.cursor()

    # create temp result table
    tempCursor = conn.cursor()
    tempCursor.execute("""
                          CREATE TEMP TABLE tmp_result
                          (
                            station_id INTEGER,
                            item_id INTEGER
                          )
                       """)

    stmtInsert = "INSERT INTO tmp_result(station_id, item_id) VALUES(?, ?)"

    # check if the stations pays more than it's asking
    for (stationID, itemID, sell, buy) in checkCursor.execute("""
                             SELECT si.station_id, si.item_id,
                                    si.demand_price, si.supply_price
                               FROM StationItem AS si
                              WHERE si.demand_price > si.supply_price
                                AND si.supply_price > 0
                        """):
        cmdenv.DEBUG0("sell > buy: {:>7n} > {:>7n}".format(sell, buy))
        tempCursor.execute(stmtInsert, [stationID, itemID])

    # check if sell = buy = stock
    for (stationID, itemID, sell, buy) in checkCursor.execute("""
                             SELECT si.station_id, si.item_id,
                                    si.demand_price, si.supply_price
                               FROM StationItem AS si
                              WHERE si.demand_price > 0
                                AND si.demand_price = si.supply_price
                                AND si.supply_price = si.supply_units
                        """):
        cmdenv.DEBUG0("sell = buy = stock: {:>7n} = {:>7n}".format(sell, buy))
        tempCursor.execute(stmtInsert, [stationID, itemID])

    # check if buy > sell * (10/7)
    for (stationID, itemID, sell, buy) in checkCursor.execute("""
                             SELECT si.station_id, si.item_id,
                                    si.demand_price, si.supply_price
                               FROM StationItem AS si
                              WHERE si.supply_price > round(si.demand_price*10.0/7)
                                AND si.demand_price > {}
                        """.format("-1" if cmdenv.detail > 1 else "0")):
        cmdenv.DEBUG0("buy > sell * (10/7): {:>7n} > {:>7n}".format(buy, int(sell*4/3)))
        tempCursor.execute(stmtInsert, [stationID, itemID])

    # sql statement for rounded min/max check
    stmtAvgDev = """
                    SELECT item_id,
                           CASE
                             WHEN price < 10 THEN           price
                             WHEN price < 100 THEN    ROUND(price*1.0/10)*10
                             WHEN price < 1000 THEN   ROUND(price*1.0/100)*100
                             WHEN price < 10000 THEN  ROUND(price*1.0/1000)*1000
                             WHEN price < 100000 THEN ROUND(price*1.0/10000)*10000
                             ELSE price
                           END AS round_price,
                           MIN(price) AS min_price,
                           MAX(price) AS max_price,
                           COUNT(*) AS count_price
                      FROM {table}
                     GROUP BY 1,2
                 """

    # sql statement for price checking
    stmtPrice = """
                   INSERT INTO tmp_result(station_id, item_id)
                     SELECT station_id, item_id
                       FROM {table}
                      WHERE item_id = ?
                        AND {badStmt}
                """

    # check rounded min/max for prices
    for tableName in ('StationBuying', 'StationSelling'):
        badStmt   = []
        oldItemID = -1
        for (itemID, dummy, minPrice, maxPrice, countPrice) in itemCursor.execute(stmtAvgDev.format(table=tableName)):
            if oldItemID != itemID:
                if len(badStmt) > 0:
                    badSQL = buildPriceSQL(badStmt)
                    cmdenv.DEBUG1(" ".join(stmtPrice.format(table=tableName,badStmt=badSQL).split()))
                    checkCursor.execute(stmtPrice.format(table=tableName,
                                                         badStmt=badSQL),
                                        [ oldItemID ])
                    del badStmt[:]
                oldItemID = itemID
            if countPrice > checkCount:
                cmdenv.DEBUG1(", ".join(str(x) for x in (itemID, dummy, minPrice, maxPrice, countPrice))+" (good)")
            else:
                cmdenv.DEBUG0(", ".join(str(x) for x in (itemID, dummy, minPrice, maxPrice, countPrice))+" (bad)")
                badStmt.append(buildPriceStmt(minPrice, maxPrice))
        if len(badStmt) > 0:
            badSQL = buildPriceSQL(badStmt)
            cmdenv.DEBUG1(" ".join(stmtPrice.format(table=tableName,badStmt=badSQL).split()))
            checkCursor.execute(stmtPrice.format(table=tableName,
                                                 badStmt=badSQL),
                                [ itemID ])

    # sql statement for the result list
    sqlStmt = """
                 SELECT DISTINCT Station.station_id, Item.item_id,
                                 IFNULL(si.demand_price, 0) AS demand_price,
                                 IFNULL(si.supply_price, 0) AS supply_price
                   FROM tmp_result AS t
                        INNER JOIN Item    USING(item_id)
                        INNER JOIN Category ON Category.category_id = Item.category_id
                        INNER JOIN Station USING(station_id)
                        INNER JOIN System ON System.system_id = Station.system_id
                        LEFT OUTER JOIN StationItem AS si
                             USING (item_id, station_id)
                  ORDER BY System.name, Station.name, Category.name, Item.name
              """

    results.rows = []
    for resRow in tempCursor.execute(sqlStmt):
        results.rows.append(resRow)

    return results

#######################################################################
## Transform result set into output

def render(results, cmdenv, tdb):
    from formatting import RowFormat, ColumnFormat

    rowCount = len(results.rows)
    if rowCount == 0:
        print("No suspicious prices found.")
    else:
        if rowCount == 1:
            print("One suspicious price found.")
        else:
            print("{} suspicious prices found.".format(rowCount))
        print()

        itemByID     = tdb.itemByID
        stationByID  = tdb.stationByID

        itemRowFmt = RowFormat()
        longestNamed = max(results.rows, key=lambda result: len(stationByID[result['station_id']].system.str()))
        longestNameLen = len(stationByID[longestNamed['station_id']].system.str())
        itemRowFmt.addColumn('System', '<', longestNameLen,
            key=lambda row: stationByID[row['station_id']].system.str())

        longestNamed = max(results.rows, key=lambda result: len(stationByID[result['station_id']].str()))
        longestNameLen = len(stationByID[longestNamed['station_id']].str())
        itemRowFmt.addColumn('Station', '<', longestNameLen,
            key=lambda row: stationByID[row['station_id']].str())

        longestNamed = max(results.rows, key=lambda result: len(itemByID[result['item_id']].dbname))
        longestNameLen = len(itemByID[longestNamed['item_id']].dbname)
        itemRowFmt.addColumn('Item', '<', longestNameLen,
            key=lambda row: itemByID[row['item_id']].dbname)

        itemRowFmt.addColumn('Sell Cr', '>', 7, 'n',
            key=lambda row: row['demand_price'])
        itemRowFmt.addColumn('Buy Cr', '>', 7, 'n',
            key=lambda row: row['supply_price'])

        if not cmdenv.quiet:
            heading, underline = itemRowFmt.heading()
            print(heading, underline, sep='\n')

        for row in results.rows:
            print(itemRowFmt.format(row))
