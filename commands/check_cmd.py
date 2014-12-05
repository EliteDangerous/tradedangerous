from __future__ import absolute_import, with_statement, print_function, division, unicode_literals
from commands.parsing import MutuallyExclusiveGroup, ParseArgument
from commands.exceptions import *
import sqlite3
import math

######################################################################
# Parser config

help='Check item prices and report suspicious entries.'
name='check'
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
    results.rows = []
    devCount  = 99
    devFactor = 3.5
    checkCursor = conn.cursor()

    # create temp result table
    tempCursor = conn.cursor()
    tempCursor.execute("""
                          CREATE TEMP TABLE tmp_check
                          (
                            station_id INTEGER,
                            item_id INTEGER
                          )
                       """)

    # sql statement for average and standard deviation
    stmtAvgDev = """
                    SELECT count(*), round(avg(price)), round(stddev(price))
                      FROM {table} AS a
                     WHERE item_id = ?
                 """

    # sql statement for price checking
    stmtPrice = """
                   INSERT INTO tmp_check(station_id, item_id)
                     SELECT {table}.station_id, {table}.item_id
                       FROM {table}
                      WHERE {table}.item_id = ?
                        AND {table}.price NOT BETWEEN ? AND ?
                """

    for item in tdb.items():
        # check if the stations pays more than it's asking
        checkCursor.execute("""
                               INSERT INTO tmp_check(station_id, item_id)
                                 SELECT vPrice.station_id, vPrice.item_id
                                   FROM vPrice
                                  WHERE vPrice.item_id = ?
                                    AND vPrice.sell_to > vPrice.buy_from
                                    AND vPrice.buy_from > 0
                            """, [ item.ID ])

        # check if sell = buy = stock
        checkCursor.execute("""
                               INSERT INTO tmp_check(station_id, item_id)
                                 SELECT vPrice.station_id, vPrice.item_id
                                   FROM vPrice
                                  WHERE vPrice.item_id = ?
                                    AND vPrice.sell_to > 0
                                    AND vPrice.sell_to = vPrice.buy_from
                                    AND vPrice.buy_from = vPrice.stock
                            """, [ item.ID ])

        # check average and standard deviation for prices
        for tableName in ('StationBuying', 'StationSelling'):
            checkCursor.execute(stmtAvgDev.format(table=tableName), [ item.ID ])
            countPrice, avgPrice, devPrice = checkCursor.fetchone()
            if countPrice > devCount and avgPrice and devPrice:
                minPrice = avgPrice - devPrice*devFactor
                maxPrice = avgPrice + devPrice*devFactor
                print(item.dbname, countPrice, avgPrice, devPrice, minPrice, maxPrice)
                checkCursor.execute(stmtPrice.format(table=tableName),
                                    [ item.ID, minPrice, maxPrice ])

    # sql statement for the result
    sqlStmt = """
                 SELECT DISTINCT Station.station_id, Item.item_id,
                                 IFNULL(sb.price, 0) AS sell_to,
                                 IFNULL(ss.price, 0) AS buy_from
                   FROM tmp_check AS t
                        INNER JOIN Item    USING(item_id)
                        INNER JOIN Category ON Category.category_id = Item.category_id
                        INNER JOIN Station USING(station_id)
                        INNER JOIN System ON System.system_id = Station.system_id
                        LEFT OUTER JOIN StationBuying AS sb
                             USING (item_id, station_id)
                        LEFT OUTER JOIN StationSelling AS ss
                             USING (station_id, item_id)
                  ORDER BY System.name, Station.name, Category.name, Item.name
              """

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
            key=lambda row: row['sell_to'])
        itemRowFmt.addColumn('Buy Cr', '>', 7, 'n',
            key=lambda row: row['buy_from'])

        if not cmdenv.quiet:
            heading, underline = itemRowFmt.heading()
            print(heading, underline, sep='\n')

        for row in results.rows:
            print(itemRowFmt.format(row))
