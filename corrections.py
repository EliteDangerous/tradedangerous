# Provides an interface for correcting star/station names that
# have changed in recent versions.

from __future__ import absolute_import, with_statement, print_function, division, unicode_literals

# Arbitrary, negative value to denote something that's been removed.
DELETED = -111

systems = {
    "PANDAMONIUM": "PANDEMONIUM",
    "ARGETLÁMH": "ARGETLAMH",
    "LíFTHRUTI": "LIFTHRUTI",
    "MANTóAC": "MANTOAC",
    "NANTóAC": "NANTOAC",

#ADD_SYSTEMS_HERE
}

stations = {
}

categories = {
}

items = {
    'META ALLOYS': 'Meta-Alloys',
    'MU TOM IMAGER': 'Muon Imager',
    'SKIMER COMPONENTS': 'Skimmer Components',
	'POWER TRANSFER CONDUITS': 'Power Transfer Bus',
	'LOW TEMPERATURE DIAMOND': 'Low Temperature Diamonds'
}

def correctSystem(oldName):
    try:
        return systems[oldName.upper()]
    except KeyError:
        return oldName


def correctStation(systemName, oldName):
    try:
        return stations[systemName.upper() + "/" + oldName.upper()]
    except KeyError:
        return oldName


def correctCategory(oldName):
    try:
        return categories[oldName.upper()]
    except KeyError:
        return oldName


def correctItem(oldName):
    try:
        return items[oldName.upper()]
    except KeyError:
        return oldName
