# Provides an interface for correcting star/station names that
# have changed in recent versions.

from __future__ import absolute_import, with_statement, print_function, division, unicode_literals

# Arbitrary, negative value to denote something that's been removed.
DELETED = -111

systems = {
    "LTT 4549": "Shinrarta Dezhra",
    "KAMCHAULTULTULA": "Aiabiko",
#ADD_SYSTEMS_HERE
}

stations = {
    "STYX/STYX-STATION": "Searfoss Plant",
    "STYX/CHI HUB": "Searfoss Plant",
    "STYX/CHU HUB": "Searfoss Plant",
    "LFT 926/ONIZUKA PLATFORM": "Meredith City",
#ADD_STATIONS_HERE
}

categories = {
    'DRUGS':            'Legal Drugs',
}

items = {
    'HYDROGEN FUELS':   'Hydrogen Fuel',
    'MARINE SUPPLIES':  'Marine Equipment',
    'TERRAIN ENRICH SYS': 'Land Enrichment Systems',
    'HEL-STATIC FURNACES': 'Microbial Furnaces',
    'REACTIVE ARMOR': 'Reactive Armour',
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
        pass
    try:
        return stations[oldName.upper()]
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

