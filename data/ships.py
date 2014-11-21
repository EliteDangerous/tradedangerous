# List of ships known to tradedb

from __future__ import absolute_import, with_statement, print_function, division, unicode_literals
from collections import namedtuple

class Ship(namedtuple('Ship', [ 'name', 'capacity', 'mass', 'driveRating', 'maxJump', 'maxJumpFull', 'maxSpeed', 'boostSpeed', 'stations' ])):
    pass

ships = [
    #     Name           Cap   Mass   Rating  MaxLy  FullLy  Speed  Boost
    Ship('Eagle',          6,    52,    348,   6.59,   6.00,   240,   350, [ 'Abnett', 'Aulin Enterprise', 'Beagle2', 'Bradfield', 'Hay Point', 'Lacaille Prosp' ]),
    Ship('Sidewinder',     4,    47,    348,   8.13,   7.25,   220,   293, [ 'Abnett', 'Aulin Enterprise', 'Beagle2', 'Bradfield', 'Hay Point', 'Lacaille Prosp', 'Vonarburg Co-op' ]),
    Ship('Hauler',        16,    39,    348,   8.74,   6.10,   200,   246, [ 'Aulin Enterprise', 'Beagle2', 'Bradfield', 'Hay Point', 'Lacaille Prosp', 'Vonarburg Co-op' ]),
    Ship('Viper',          8,    40,    348,  13.49,   9.16,   320,   500, [ 'Aulin Enterprise', 'Beagle2', 'Bradfield', 'Chango Dock', 'Hay Point', 'Lacaille Prosp' ]),
    Ship('Cobra',         36,   114,   1155,   9.94,   7.30,   280,   400, [ 'Aulin Enterprise', 'Chango Dock' ]),
    Ship('Lakon Type 6', 100,   113,   3455,  29.36,  15.64,   220,   329, [ 'Aulin Enterprise', 'Chango Dock', 'Vonarburg Co-op' ]),
    Ship('Lakon Type 9', 440,  1275,  23720,  18.22,  13.34,   130,   200, [ 'Chango Dock' ]),
    Ship('Anaconda',     228,  2600,  52345,  19.70,  17.60,   180,   235, [ 'Lacaille Prosp' ]),
]
